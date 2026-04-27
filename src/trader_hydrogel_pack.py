"""
Prosperity 4 — Round 3 Trader for HYDROGEL_PACK only. v2.

What changed vs v1 (after backtest 460346 — final PnL -3,536):
    1. TAKE-buy / TAKE-sell layers REMOVED. v1 took 26 asks / 0 bids in 1k
       ticks because wall_mid only beats raw mid by ~0.5 RMS — far below
       the cost of crossing the touch. The take layer was the dominant
       loss source and was structurally long-biased on this product
       (bid_1 < wall_mid is essentially always true given the 16-wide
       spread, so the symmetric sell-take never fires).
    2. POSITION-SKEW added on the maker quotes. The maker layer in v1
       worked (both maker BUYs at +7 edge and maker SELLs at +7 edge),
       but inventory was allowed to drift to +158/200 on a falling day
       and the MTM swing dwarfed the realized edge. v2 skews the quote
       PRICES symmetrically by `floor(position / SKEW_DIVISOR)` so when
       long we both lower our ask (sell first) and lower our bid (don't
       buy more); when short, the opposite. This is the standard
       Avellaneda-Stoikov inventory bias.
    3. HARD INVENTORY CUTOFF at ±HARD_CAP. Past that level, only the
       reducing side is posted (e.g. above pos=120 we only sell). A
       random-walk product with no mean-reversion anchor cannot afford
       letting inventory drift; v1's soft taper engaged too late.
    4. Imbalance skew kept but with a smaller threshold and only nudges
       quote PRICE by 1 unit. In the 460346 run imbalance stayed at 0
       on virtually every tick so this layer is mostly cosmetic; the
       real inventory bias is from change 2.
    5. Maker quotes now sit at best_bid+QUOTE_DEPTH / best_ask-QUOTE_DEPTH.
       v1 used +1 / -1 (i.e. 7 inside the 16-wide touch). v2 default is
       still 1, but the parameter is exposed so backtest grid-search can
       adjust it from a single constant.

Strategy summary (analysis: notebooks/round3_hydrogel_pack.ipynb,
results/hydrogel_pack_analysis/FINDINGS.md):
    HYDROGEL_PACK is a slow random-walk true price + small noise. Range
    [9891, 10079] across the 3 historical days, std ~32. Spread fixed at
    16 on >92% of ticks. Bots quote symmetric size (~37 per side) at
    roughly mid ± 8. Trade flow is uninformative (corr ≈ 0 with forward
    returns) — fills are not adversarially selected, so pure
    market-making is safe. Best fair-value estimator: wall_mid. Best
    short-horizon signal: order-book imbalance (corr -0.33 at lag 1, but
    fires only on ~10% of ticks).

    v2 strategy = single layer:
      Quote at best_bid + QUOTE_DEPTH / best_ask - QUOTE_DEPTH around
      wall_mid, with quote prices skewed AGAINST current inventory and
      WITH the imbalance contrarian signal. Hard inventory cutoff stops
      adding to a position past HARD_CAP. No taking — wall_mid is too
      noisy a fair value to cross the touch on.

Framework notes (algorithm_examples.md):
    - run() must return (orders_dict, conversions, traderData).
    - OrderDepth.sell_orders volumes are NEGATIVE; flip sign when reading.
    - Position-limit rejection is all-or-nothing per side per product
      per tick → size each side against current position.
    - Stateless trader; traderData is always "".
    - bid() is a no-op placeholder for Round 2 compatibility.
"""

from typing import Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState


class Trader:
    POSITION_LIMIT: Dict[str, int] = {
        "HYDROGEL_PACK": 200,
    }

    # --- HYDROGEL_PACK parameters -------------------------------------------
    # Per-side maker quote size cap. Bigger = more fills, more inventory
    # turnover. Bot side-volume mean is ~37; staying at or below that keeps
    # us from being the dominant resting order at our price level.
    HP_QUOTE_SIZE = 25

    # How many ticks inside the touch our quotes sit. 1 means best_bid+1 /
    # best_ask-1 (so 7 inside on each side of a 16-wide spread). Lower =
    # more aggressive (more fills, less edge).
    HP_QUOTE_DEPTH = 1

    # Inventory skew. Quote prices shift by floor(|pos| / SKEW_DIVISOR)
    # ticks against the position direction. With divisor=30 and pos=+90,
    # we shift both quotes down by 3 — making us a much keener seller and
    # a less keen buyer. This is the standard market-maker inventory
    # bias and is the main fix vs v1.
    HP_SKEW_DIVISOR = 30

    # Hard inventory cutoff. At |pos| > HARD_CAP we stop posting on the
    # side that would grow the position further. Set well below the 200
    # limit so a multi-tick fill burst on the wrong side cannot still
    # breach it. v1 reached pos=158 with 200-limit — clearly too loose.
    HP_HARD_CAP = 120

    # Imbalance skew (contrarian). Mostly dormant on this product since
    # ~90% of ticks have bid_vol == ask_vol exactly. When it fires, just
    # nudge both quote prices by 1 in the contrarian direction.
    HP_IMB_THRESHOLD = 0.05
    HP_IMB_SKEW = 1

    # ------------------------------------------------------------------------
    def run(
        self, state: TradingState
    ) -> Tuple[Dict[str, List[Order]], int, str]:
        result: Dict[str, List[Order]] = {}

        if "HYDROGEL_PACK" in state.order_depths:
            result["HYDROGEL_PACK"] = self._trade_hydrogel_pack(
                state.order_depths["HYDROGEL_PACK"],
                state.position.get("HYDROGEL_PACK", 0),
            )

        return result, 0, ""

    def bid(self) -> None:
        return None

    # ------------------------------------------------------------------------
    @staticmethod
    def _wall_mid(order_depth: OrderDepth) -> float:
        wall_bid = max(
            order_depth.buy_orders.items(), key=lambda kv: kv[1]
        )[0]
        wall_ask = max(
            order_depth.sell_orders.items(), key=lambda kv: abs(kv[1])
        )[0]
        return (wall_bid + wall_ask) / 2

    @staticmethod
    def _imbalance(order_depth: OrderDepth) -> float:
        bid_vol = sum(order_depth.buy_orders.values())
        ask_vol = sum(abs(v) for v in order_depth.sell_orders.values())
        denom = bid_vol + ask_vol
        if denom == 0:
            return 0.0
        return (bid_vol - ask_vol) / denom

    # ------------------------------------------------------------------------
    def _trade_hydrogel_pack(
        self, order_depth: OrderDepth, position: int
    ) -> List[Order]:
        """
        Single-layer maker quote with inventory-skew + imbalance-skew.

        - quote prices = best_bid + DEPTH / best_ask - DEPTH
        - then shift BOTH prices by:
              -floor(position / SKEW_DIVISOR)        (inventory-against)
              -sign(imbalance) * IMB_SKEW            (contrarian)
        - skip the side that would grow position past HARD_CAP
        - skip if my_bid >= my_ask after shifts (crossed)
        - skip if my_bid >= wall_mid or my_ask <= wall_mid (negative EV
          vs our fair value estimate)
        """
        orders: List[Order] = []
        symbol = "HYDROGEL_PACK"
        limit = self.POSITION_LIMIT[symbol]

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        wall_mid = self._wall_mid(order_depth)
        imbalance = self._imbalance(order_depth)

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())

        # If the touch is already tight, skip — no edge to harvest.
        if best_ask - best_bid <= 2:
            return orders

        # Inventory skew: shift quote prices AGAINST the current position.
        # +position → shift down (sell more eagerly, buy less eagerly).
        inv_skew = -(position // self.HP_SKEW_DIVISOR)

        # Imbalance skew: contrarian. Bid-heavy book → expect price down
        # → shift quotes down. Ask-heavy → shift up. Mostly dormant here
        # because imbalance is exactly 0 on ~90% of ticks.
        imb_skew = 0
        if imbalance > self.HP_IMB_THRESHOLD:
            imb_skew = -self.HP_IMB_SKEW
        elif imbalance < -self.HP_IMB_THRESHOLD:
            imb_skew = +self.HP_IMB_SKEW

        total_skew = inv_skew + imb_skew

        my_bid = best_bid + self.HP_QUOTE_DEPTH + total_skew
        my_ask = best_ask - self.HP_QUOTE_DEPTH + total_skew

        # Don't post crossed.
        if my_bid >= my_ask:
            return orders

        # Position-limit headroom (per-side).
        buy_capacity = limit - position
        sell_capacity = limit + position

        # Hard inventory cutoff: above HARD_CAP we stop adding on that side.
        post_buy = position < self.HP_HARD_CAP
        post_sell = position > -self.HP_HARD_CAP

        # Positive-EV filter against wall_mid.
        if post_buy and buy_capacity > 0 and my_bid < wall_mid:
            size = min(self.HP_QUOTE_SIZE, buy_capacity)
            if size > 0:
                orders.append(Order(symbol, my_bid, size))

        if post_sell and sell_capacity > 0 and my_ask > wall_mid:
            size = min(self.HP_QUOTE_SIZE, sell_capacity)
            if size > 0:
                orders.append(Order(symbol, my_ask, -size))

        return orders
