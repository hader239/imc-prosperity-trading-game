"""
Prosperity 4 — Tutorial Round Trader.

Strategy summary (derived from analysis in notebooks/tutorial_round.ipynb):

EMERALDS — pinned at 10000
    Book is in one of three states on ~100% of ticks:
        (bid=9992, ask=10008)  96.8%  "normal"
        (bid=9992, ask=10000)   1.6%  "ask tightens"
        (bid=10000, ask=10008)  1.6%  "bid tightens"
    Fair value is 10000 everywhere. We passively quote 9999 / 10001 so we
    sit inside the normal book by a large margin and still win one side
    of the tight states. Anyone who crosses the spread trades against us.

TOMATOES — two-layer trader (take + passive quote) around wall_mid.
    wall_mid (midpoint of the largest-volume bid and ask levels) is our
    fair-value estimate: +0.62 correlation with next-tick mid change at
    h=1, ~2x stronger than microprice, stable across both sample days.
    See notebooks/fair_price_tomatoes.ipynb.

    Market structure (from analysis of submissions 64808 / 64864):
      - 93.75% of ticks are "normal" state, spread 13-14.
      - 6.25% of ticks are "narrow" state, spread 5-9. These are
        exactly the ticks where |wall_mid - mid| > 1 — the narrow
        spread and the signal are the same event.
      - On narrow ticks, someone jams a resting order through fair
        (e.g. ask=5001 while wall_mid=5002). Across 125 narrow ticks
        in 64808, our passive quotes at best_bid+1 / best_ask-1 got
        exactly 0 fills: the counterparty flow on those ticks never
        reaches our quotes. Alpha lives in *taking*, not making.
      - Submission 64744 confirmed the opposite failure mode: quoting
        deeper into the book (floor(wall_mid ± k)) cut both fill rate
        and per-fill edge in the normal state.

    Strategy:
      1. TAKE: walk the book. While ask < wall_mid, buy. While
         bid > wall_mid, sell. Same pattern as EMERALDS, but with
         wall_mid as a dynamic fair. Captures the narrow-state alpha.
      2. QUOTE: in the normal state (spread > 2), post passive maker
         quotes at best_bid+1 / best_ask-1 to earn the spread. Guarded
         by a positive-EV filter (my_bid < wall_mid, my_ask > wall_mid)
         to skip the ~3% of ticks where top-of-book has crossed fair.

Framework notes (see algorithm_examples.md):
    - run() must return (orders_dict, conversions, traderData).
    - OrderDepth.sell_orders volumes are NEGATIVE; flip sign when reading.
    - Position-limit rejection is all-or-nothing per product per tick, so
      every order must be sized against current position.
    - This trader is stateless; traderData is always "".
    - bid() is a no-op placeholder for Round 2 compatibility.
"""

from typing import Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState


class Trader:
    POSITION_LIMIT: Dict[str, int] = {
        "EMERALDS": 80,
        "TOMATOES": 80,
    }

    # ------------------------------------------------------------------------
    def run(
        self, state: TradingState
    ) -> Tuple[Dict[str, List[Order]], int, str]:
        result: Dict[str, List[Order]] = {}

        if "EMERALDS" in state.order_depths:
            result["EMERALDS"] = self._trade_emeralds(
                state.order_depths["EMERALDS"],
                state.position.get("EMERALDS", 0),
            )

        if "TOMATOES" in state.order_depths:
            result["TOMATOES"] = self._trade_tomatoes(
                state.order_depths["TOMATOES"],
                state.position.get("TOMATOES", 0),
            )

        return result, 0, ""

    def bid(self) -> None:
        """Required shape for Round 2; unused in the tutorial round."""
        return None

    # --- EMERALDS parameters ------------------------------------------------
    EMERALDS_FAIR = 10000
    # Quote offset from fair value. 7 chosen so we sit just inside the normal
    # book state (9992/10008) while still the best bid and ask by a wide
    # margin. Earns 7 per unit per fill instead of 1 with fair±1. See
    # submission 63761 analysis: EMERALDS was fill-count-limited, not
    # size-limited, so widening the spread multiplies PnL per fill at the
    # same fill count.
    EMERALDS_QUOTE_OFFSET = 7
    EMERALDS_QUOTE_SIZE = 20  # size we post on each side of our quote

    # ------------------------------------------------------------------------
    def _trade_emeralds(
        self, order_depth: OrderDepth, position: int
    ) -> List[Order]:
        """
        Simple market-making around a fixed fair value of 10000.
        1. Take any resting ask priced strictly below fair (buy cheap).
        2. Take any resting bid priced strictly above fair (sell high).
        3. Post passive quotes at fair-1 and fair+1 with whatever capacity
           remains after the takes.
        """
        orders: List[Order] = []
        fair = self.EMERALDS_FAIR
        limit = self.POSITION_LIMIT["EMERALDS"]

        # -- Step 1: take cheap asks --------------------------------------
        # sell_orders: {price: negative_volume}; sort ascending (cheapest first)
        for ask_price in sorted(order_depth.sell_orders.keys()):
            if ask_price >= fair:
                break
            available = -order_depth.sell_orders[ask_price]
            room = limit - position
            if room <= 0:
                break
            qty = min(available, room)
            orders.append(Order("EMERALDS", ask_price, qty))
            position += qty

        # -- Step 2: take rich bids ---------------------------------------
        # buy_orders: {price: positive_volume}; sort descending (richest first)
        for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
            if bid_price <= fair:
                break
            available = order_depth.buy_orders[bid_price]
            room = limit + position  # can sell until we hit -limit
            if room <= 0:
                break
            qty = min(available, room)
            orders.append(Order("EMERALDS", bid_price, -qty))
            position -= qty

        # -- Step 3: passive quotes inside the book ----------------------
        buy_capacity = limit - position
        sell_capacity = limit + position

        best_ask = min(order_depth.sell_orders.keys())
        best_bid = max(order_depth.buy_orders.keys())
        #offset = self.EMERALDS_QUOTE_OFFSET

        if buy_capacity > 0 and best_bid < fair:
            size = buy_capacity #min(self.EMERALDS_QUOTE_SIZE, buy_capacity)
            orders.append(Order("EMERALDS", best_bid + 1, size))

        if sell_capacity > 0 and best_ask > fair:
            size = sell_capacity #min(self.EMERALDS_QUOTE_SIZE, sell_capacity)
            orders.append(Order("EMERALDS", best_ask - 1, -size))

        return orders

    # --- TOMATOES parameters ------------------------------------------------
    # Per-tick cap on passive quote size; distinct from the position limit.
    # Bounds how much we can be filled in a single tick via our maker quotes.
    # The take layer is NOT capped by this — it respects the position limit
    # and the available book depth only.
    TOMATOES_QUOTE_SIZE = 20

    # ------------------------------------------------------------------------
    def _wall_mid(self, order_depth: OrderDepth) -> float:
        """Midpoint of the largest-volume bid and largest-volume ask levels.

        Sell-side volumes are stored as negatives in OrderDepth, so compare
        them by absolute value.
        """
        wall_bid = max(order_depth.buy_orders.items(), key=lambda kv: kv[1])[0]
        wall_ask = max(
            order_depth.sell_orders.items(), key=lambda kv: abs(kv[1])
        )[0]
        return (wall_bid + wall_ask) / 2

    # ------------------------------------------------------------------------
    def _trade_tomatoes(
        self, order_depth: OrderDepth, position: int
    ) -> List[Order]:
        """
        Two-layer strategy around wall_mid (see module docstring for the
        market-structure reasoning):

        1. Take any resting ask strictly below wall_mid (buy cheap).
        2. Take any resting bid strictly above wall_mid (sell rich).
        3. Post passive quotes at best_bid+1 / best_ask-1 in the
           normal-state book (spread > 2), guarded by a positive-EV
           filter against wall_mid.

        Position updates after takes are carried into the passive-quote
        capacity calculation so we never breach the position limit.
        """
        orders: List[Order] = []
        limit = self.POSITION_LIMIT["TOMATOES"]

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders  # one side of the book is empty; stay out

        wall_mid = self._wall_mid(order_depth)

        # -- Step 1: take cheap asks (buy below wall_mid) ----------------
        for ask_price in sorted(order_depth.sell_orders.keys()):
            if ask_price >= wall_mid:
                break
            available = -order_depth.sell_orders[ask_price]
            room = limit - position
            if room <= 0:
                break
            qty = min(available, room)
            orders.append(Order("TOMATOES", ask_price, qty))
            position += qty

        # -- Step 2: take rich bids (sell above wall_mid) ---------------
        for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
            if bid_price <= wall_mid:
                break
            available = order_depth.buy_orders[bid_price]
            room = limit + position
            if room <= 0:
                break
            qty = min(available, room)
            orders.append(Order("TOMATOES", bid_price, -qty))
            position -= qty

        # -- Step 3: passive maker quotes in the normal state -----------
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())

        # Tight book: best_bid+1 and best_ask-1 would overlap. Skip the
        # passive layer (but the taking above already ran).
        if best_ask - best_bid <= 2:
            return orders

        my_bid = best_bid + 1
        my_ask = best_ask - 1

        buy_capacity = limit - position
        sell_capacity = limit + position

        # Positive-EV filter: only post each side if the resulting trade
        # would be profitable against wall_mid. Blocks the ~3% of ticks
        # where top-of-book has crossed fair.
        if buy_capacity > 0 and my_bid < wall_mid:
            size = min(self.TOMATOES_QUOTE_SIZE, buy_capacity)
            orders.append(Order("TOMATOES", my_bid, size))

        if sell_capacity > 0 and my_ask > wall_mid:
            size = min(self.TOMATOES_QUOTE_SIZE, sell_capacity)
            orders.append(Order("TOMATOES", my_ask, -size))

        return orders
