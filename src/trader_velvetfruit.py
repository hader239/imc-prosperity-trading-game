"""
Round 3 single-product trader for VELVETFRUIT_EXTRACT — v2 (Tier 1 fixes).

Strategy (derived from results/findings_velvetfruit_extract.md):
  - Fair value = Wall Mid (EMA-smoothed). Beats raw mid and microprice.
  - Take obvious mispricings, with an inventory-aware threshold so we don't
    aggress further into trouble when already heavily long/short.
  - Layered passive quotes (3 levels per side), anchored on a reservation
    price that's pulled toward zero inventory and leaned against the
    fv_gap mean-reversion signal.
  - Asymmetric quote sizes: shrink the side that would grow inventory and
    grow the side that would unwind it.

State persisted in traderData (jsonpickle): just the EMA of wall_mid.

v2 changes vs v1:
  - INVENTORY_SKEW 0.02 -> 0.05 (stronger pull back to flat)
  - Inventory-aware take threshold (don't lift asks while heavy long)
  - Three-level layered passive quotes
  - Position-aware quote sizing per side (shrink side that grows inventory)
"""

from typing import Dict, List, Tuple
import jsonpickle

from datamodel import Order, OrderDepth, TradingState


PRODUCT = "VELVETFRUIT_EXTRACT"
POSITION_LIMIT = 200


class Trader:
    # ---- tunable parameters ----
    EMA_ALPHA = 0.30          # higher = more reactive, lower = smoother
    HALF_SPREAD = 1.5         # innermost quote distance from reservation
    INVENTORY_SKEW = 0.05     # per-unit pull of reservation toward zero pos
    GAP_LEAN = 0.6            # how much to lean against the fv_gap signal
    TAKE_BASE = 1.5           # base take threshold (in ticks through fair)
    TAKE_INV_PENALTY = 0.05   # per-unit add'l threshold when already loaded
    MAX_QUOTE_SIZE = 25       # passive quote size for the favorable side
    QUOTE_SHRINK_PER_UNIT = 0.5  # shrink unfavorable side: size - 0.5*|pos|
    LAYER_OFFSETS = (1, 2, 3)    # multiplier on HALF_SPREAD per layer
    LAYER_WEIGHTS = (0.5, 0.3, 0.2)  # size split across layers (sum=1)
    # Per-layer max distance from the touch (in ticks). Caps quotes so layered
    # passives don't end up crossing toward the wrong side when the EMA lags.
    LAYER_TOUCH_OFFSETS = (1, 0, -1)  # +1 = inside spread, 0 = at touch, -1 = below

    # ---- helpers ----
    @staticmethod
    def _wall_price(levels: Dict[int, int]) -> int | None:
        """Return the price of the level with the largest |volume|."""
        if not levels:
            return None
        return max(levels.items(), key=lambda kv: abs(kv[1]))[0]

    def _fair_value(self, depth: OrderDepth, ema: float | None) -> Tuple[float, float | None]:
        """Return (updated_ema, raw_mid). Falls back gracefully on partial books."""
        if not depth.buy_orders or not depth.sell_orders:
            return (ema if ema is not None else 0.0, None)

        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        raw_mid = (best_bid + best_ask) / 2

        wall_bid = self._wall_price(depth.buy_orders)
        wall_ask = self._wall_price(depth.sell_orders)
        wall_mid = (wall_bid + wall_ask) / 2 if wall_bid is not None and wall_ask is not None else raw_mid

        new_ema = wall_mid if ema is None else self.EMA_ALPHA * wall_mid + (1 - self.EMA_ALPHA) * ema
        return new_ema, raw_mid

    def _layered_quotes(
        self,
        side: str,
        reservation: float,
        room: int,
        favorable: bool,
        best_bid: int,
        best_ask: int,
    ) -> List[Tuple[int, int]]:
        """
        Build 3 layered passive quotes for one side.
        `favorable` = True if this side unwinds inventory (use full size).
        Returns list of (price, signed_qty). Empty if no room.
        """
        if room <= 0:
            return []

        # base size: full on favorable side, shrunk on unfavorable side
        if favorable:
            base = self.MAX_QUOTE_SIZE
        else:
            # the unfavorable side is the one that would grow inventory.
            # shrink as inventory grows; never below 0.
            base = self.MAX_QUOTE_SIZE  # caller adjusts via `room` and shrink

        # split base across layers; round each, then truncate by available room
        out: List[Tuple[int, int]] = []
        remaining = room
        for offset, weight, touch_off in zip(
            self.LAYER_OFFSETS, self.LAYER_WEIGHTS, self.LAYER_TOUCH_OFFSETS
        ):
            qty = int(round(base * weight))
            if qty <= 0:
                continue
            qty = min(qty, remaining)
            if qty <= 0:
                break

            if side == "bid":
                price = int(round(reservation - offset * self.HALF_SPREAD))
                # cap by per-layer max (1 inside / at / below touch)
                # AND never cross the ask
                price = min(price, best_bid + touch_off, best_ask - 1)
                signed = qty
            else:  # ask
                price = int(round(reservation + offset * self.HALF_SPREAD))
                price = max(price, best_ask - touch_off, best_bid + 1)
                signed = -qty

            out.append((price, signed))
            remaining -= qty

        return out

    # ---- main entry point ----
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        # decode persisted state
        ema: float | None = None
        if state.traderData:
            try:
                blob = jsonpickle.decode(state.traderData)
                if isinstance(blob, dict):
                    ema = blob.get("ema")
            except Exception:
                ema = None

        depth = state.order_depths.get(PRODUCT)
        position = state.position.get(PRODUCT, 0)

        if depth is None:
            return ({}, 0, jsonpickle.encode({"ema": ema}))

        new_ema, raw_mid = self._fair_value(depth, ema)
        ema = new_ema

        if not depth.buy_orders or not depth.sell_orders or raw_mid is None:
            return ({PRODUCT: []}, 0, jsonpickle.encode({"ema": ema}))

        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        bid_vol_at_best = depth.buy_orders[best_bid]
        ask_vol_at_best = -depth.sell_orders[best_ask]

        fair = ema
        gap = raw_mid - fair  # positive => mid above fair => expect down

        # reservation: pull toward zero inventory, lean against the bounce signal
        reservation = fair - self.INVENTORY_SKEW * position - self.GAP_LEAN * gap

        # remaining room before hitting position limits
        buy_room = POSITION_LIMIT - position
        sell_room = POSITION_LIMIT + position

        orders: List[Order] = []

        # ---- 1) take obvious mispricings (inventory-aware threshold) ----
        # if we're already long, require deeper discount before buying more
        take_buy_threshold = self.TAKE_BASE + self.TAKE_INV_PENALTY * max(0, position)
        # if we're already short, require deeper premium before selling more
        take_sell_threshold = self.TAKE_BASE + self.TAKE_INV_PENALTY * max(0, -position)

        if best_ask < fair - take_buy_threshold and buy_room > 0:
            take_qty = min(ask_vol_at_best, buy_room)
            if take_qty > 0:
                orders.append(Order(PRODUCT, best_ask, take_qty))
                buy_room -= take_qty
                position += take_qty  # keep local view consistent for sizing

        if best_bid > fair + take_sell_threshold and sell_room > 0:
            take_qty = min(bid_vol_at_best, sell_room)
            if take_qty > 0:
                orders.append(Order(PRODUCT, best_bid, -take_qty))
                sell_room -= take_qty
                position -= take_qty

        # ---- 2) layered passive quotes with asymmetric sizing ----
        # the side that would *grow* inventory is "unfavorable" — shrink it.
        # bid grows long inventory; ask grows short inventory.
        bid_unfav = position > 0
        ask_unfav = position < 0

        # shrink the unfavorable side proportionally to current inventory
        bid_size_cap = self.MAX_QUOTE_SIZE
        ask_size_cap = self.MAX_QUOTE_SIZE
        if bid_unfav:
            bid_size_cap = max(0, int(self.MAX_QUOTE_SIZE - self.QUOTE_SHRINK_PER_UNIT * position))
        if ask_unfav:
            ask_size_cap = max(0, int(self.MAX_QUOTE_SIZE - self.QUOTE_SHRINK_PER_UNIT * (-position)))

        # also cap by position-limit room
        bid_room = min(bid_size_cap, max(0, buy_room))
        ask_room = min(ask_size_cap, max(0, sell_room))

        bid_layers = self._layered_quotes(
            "bid", reservation, bid_room, favorable=not bid_unfav,
            best_bid=best_bid, best_ask=best_ask,
        )
        ask_layers = self._layered_quotes(
            "ask", reservation, ask_room, favorable=not ask_unfav,
            best_bid=best_bid, best_ask=best_ask,
        )

        for price, signed_qty in bid_layers + ask_layers:
            if signed_qty != 0:
                orders.append(Order(PRODUCT, price, signed_qty))

        trader_data = jsonpickle.encode({"ema": ema})
        return ({PRODUCT: orders}, 0, trader_data)

    # Round 2 conversion-bid placeholder; harmless if unused.
    def bid(self) -> int:
        return 0
