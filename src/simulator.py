"""
Local replay simulator for the Prosperity 4 tutorial round.

Usage: reproduce past submission results or test new strategy variants
without having to upload to the Prosperity site.

--- Fill model ---
Prosperity's real simulator matches our orders against:
  (a) the visible resting order book from the CSV data, and
  (b) hidden counterparty flow from the bots.

This local simulator models (a) exactly and approximates (b) by using a
reference submission's own fills as "ground truth" for the available
passive-counterparty flow at each tick.

Specifically, for each passive fill in the reference submission at
(timestamp, price, qty), we assume the counterparty was willing to trade
up to `qty` units at a price at least as good as `price`. Any strategy
that quotes at or better than that price for that product/tick will
receive the same fill (bounded by our size).

--- Caveats ---
- This model is OPTIMISTIC for strategies that post at the same prices
  as the reference (fills should match exactly) and CONSERVATIVE for
  strategies that post at WORSE prices (we don't assume the counterparty
  would have relaxed — they might have, but we can't know).
- The take layer is modeled exactly against the resting book.
- Position-limit rejection is enforced per product per tick.
- Same-tick take ordering: we apply takes first (which reduce book
  depth in memory), then passive-quote matches, so a passive quote that
  would collide with a take is bounded by position, not double-filled.
- The simulator returns the same shape of state as the real runtime so
  trader code is unmodified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from io import StringIO
from typing import Dict, List, Tuple

import pandas as pd

from datamodel import Order, OrderDepth, TradingState


# ---------------------------------------------------------------------------
# Data model helpers
# ---------------------------------------------------------------------------


@dataclass
class GroundTruthFill:
    """A passive fill event inferred from a reference submission."""
    side: str       # 'BUY' (we bought) or 'SELL' (we sold)
    price: int
    qty: int        # positive


@dataclass
class TickState:
    timestamp: int
    order_depths: Dict[str, OrderDepth]  # product -> depth
    gt_fills: Dict[str, List[GroundTruthFill]]  # product -> list
    mid_prices: Dict[str, float]


# ---------------------------------------------------------------------------
# Loader: turn a Prosperity log into per-tick state
# ---------------------------------------------------------------------------


def _parse_activities(activities_log: str) -> pd.DataFrame:
    return pd.read_csv(StringIO(activities_log), sep=";")


def _row_to_depth(row: pd.Series) -> OrderDepth:
    od = OrderDepth()
    for i in (1, 2, 3):
        p = row[f"bid_price_{i}"]
        v = row[f"bid_volume_{i}"]
        if pd.notna(p) and pd.notna(v):
            od.buy_orders[int(p)] = int(v)
        p = row[f"ask_price_{i}"]
        v = row[f"ask_volume_{i}"]
        if pd.notna(p) and pd.notna(v):
            od.sell_orders[int(p)] = -int(v)
    return od


def load_reference(log_path: str) -> Tuple[List[TickState], Dict[str, float]]:
    """Load a reference submission log into per-tick state.

    Returns (tick_states, final_mids) where tick_states is sorted by
    timestamp and final_mids maps product -> closing mid price.
    """
    with open(log_path) as f:
        data = json.load(f)
    act = _parse_activities(data["activitiesLog"])

    trades = pd.DataFrame(data["tradeHistory"])
    sub = trades[
        (trades["buyer"] == "SUBMISSION") | (trades["seller"] == "SUBMISSION")
    ].copy()
    sub["side"] = sub["buyer"].apply(
        lambda b: "BUY" if b == "SUBMISSION" else "SELL"
    )

    # Group GT fills by (product, timestamp)
    gt_by_key: Dict[Tuple[str, int], List[GroundTruthFill]] = {}
    for _, r in sub.iterrows():
        key = (r["symbol"], int(r["timestamp"]))
        gt_by_key.setdefault(key, []).append(
            GroundTruthFill(side=r["side"], price=int(r["price"]), qty=int(r["quantity"]))
        )

    # Group activities rows by timestamp
    ticks: Dict[int, TickState] = {}
    for _, row in act.iterrows():
        ts = int(row["timestamp"])
        product = row["product"]
        if ts not in ticks:
            ticks[ts] = TickState(
                timestamp=ts, order_depths={}, gt_fills={}, mid_prices={}
            )
        ticks[ts].order_depths[product] = _row_to_depth(row)
        ticks[ts].mid_prices[product] = float(row["mid_price"])
        ticks[ts].gt_fills[product] = gt_by_key.get((product, ts), [])

    sorted_ticks = [ticks[ts] for ts in sorted(ticks.keys())]
    # Final mid per product
    final_mids: Dict[str, float] = {}
    for t in reversed(sorted_ticks):
        for p, m in t.mid_prices.items():
            if p not in final_mids:
                final_mids[p] = m
    return sorted_ticks, final_mids


# ---------------------------------------------------------------------------
# Fill engine
# ---------------------------------------------------------------------------


@dataclass
class SimFill:
    timestamp: int
    product: str
    price: int
    qty: int        # signed: +N buy, -N sell
    kind: str       # 'take' or 'passive'


@dataclass
class SimResult:
    fills: List[SimFill] = field(default_factory=list)
    pnl_by_product: Dict[str, float] = field(default_factory=dict)
    position_by_product: Dict[str, int] = field(default_factory=dict)
    cash_by_product: Dict[str, float] = field(default_factory=dict)
    total_pnl: float = 0.0


def _match_orders_for_product(
    product: str,
    orders: List[Order],
    depth: OrderDepth,
    gt_fills: List[GroundTruthFill],
    start_position: int,
    position_limit: int,
    timestamp: int,
) -> Tuple[List[SimFill], int]:
    """Match a single product's orders against the tick state.

    Returns (fills, end_position). Enforces position limits on aggregate
    buy and sell sides separately, so a mixed-direction order set where
    the aggregate would breach the limit still has ALL orders on the
    overshooting side rejected — matching Prosperity's all-or-nothing
    rule per side per product per tick.
    """
    fills: List[SimFill] = []
    position = start_position

    # --- Enforce all-or-nothing aggregate position check ---
    total_buy = sum(o.quantity for o in orders if o.quantity > 0)
    total_sell = sum(-o.quantity for o in orders if o.quantity < 0)
    buys_ok = (position + total_buy) <= position_limit
    sells_ok = (position - total_sell) >= -position_limit

    # --- Build a mutable copy of the book we can consume via takes ---
    book_sell = dict(depth.sell_orders)   # price -> negative volume
    book_buy = dict(depth.buy_orders)     # price -> positive volume

    # --- Passive GT fills available this tick ---
    gt_buy_fills = [g for g in gt_fills if g.side == "BUY"]   # we bought
    gt_sell_fills = [g for g in gt_fills if g.side == "SELL"]  # we sold
    gt_buy_remaining = {id(g): g.qty for g in gt_buy_fills}
    gt_sell_remaining = {id(g): g.qty for g in gt_sell_fills}

    # --- Step 1: process takes (order price matches a resting book level) ---
    take_orders = []
    passive_orders = []
    for o in orders:
        if o.quantity > 0 and o.price in book_sell and book_sell[o.price] < 0:
            take_orders.append(o)
        elif o.quantity < 0 and o.price in book_buy and book_buy[o.price] > 0:
            take_orders.append(o)
        else:
            passive_orders.append(o)

    for o in take_orders:
        if o.quantity > 0 and buys_ok:
            avail = -book_sell.get(o.price, 0)
            qty = min(o.quantity, avail)
            if qty <= 0:
                continue
            book_sell[o.price] = -(avail - qty)
            fills.append(SimFill(timestamp, product, o.price, qty, "take"))
            position += qty
        elif o.quantity < 0 and sells_ok:
            avail = book_buy.get(o.price, 0)
            qty = min(-o.quantity, avail)
            if qty <= 0:
                continue
            book_buy[o.price] = avail - qty
            fills.append(SimFill(timestamp, product, o.price, -qty, "take"))
            position -= qty

    # --- Step 2: process passive orders against GT fills ---
    for o in passive_orders:
        if o.quantity > 0 and buys_ok:
            # Find GT buy fills at price <= o.price (we bid better or equal)
            for g in gt_buy_fills:
                if g.price > o.price:
                    continue
                remaining = gt_buy_remaining[id(g)]
                if remaining <= 0:
                    continue
                qty = min(o.quantity, remaining)
                gt_buy_remaining[id(g)] = remaining - qty
                # Use our bid price for fill (the aggressor hit our price)
                fills.append(SimFill(timestamp, product, o.price, qty, "passive"))
                position += qty
                o_left = o.quantity - qty
                if o_left <= 0:
                    break
                # Continue if more GT fills available — but dataclass order is
                # immutable from outside; we mutate a local if needed.
                o.quantity = o_left
            # restore o.quantity is not needed because we don't use it again
        elif o.quantity < 0 and sells_ok:
            for g in gt_sell_fills:
                if g.price < o.price:
                    continue
                remaining = gt_sell_remaining[id(g)]
                if remaining <= 0:
                    continue
                qty = min(-o.quantity, remaining)
                gt_sell_remaining[id(g)] = remaining - qty
                fills.append(SimFill(timestamp, product, o.price, -qty, "passive"))
                position -= qty
                o_left = -o.quantity - qty
                if o_left <= 0:
                    break
                o.quantity = -o_left

    return fills, position


def simulate(
    trader,
    tick_states: List[TickState],
    final_mids: Dict[str, float],
    position_limits: Dict[str, int],
    start_positions: Dict[str, int] = None,
) -> SimResult:
    """Run a Trader through a sequence of ticks and collect fills/PnL."""
    positions: Dict[str, int] = dict(start_positions or {})
    cash: Dict[str, float] = {}
    all_fills: List[SimFill] = []

    for tick in tick_states:
        state = TradingState(
            traderData="",
            timestamp=tick.timestamp,
            listings={},
            order_depths=tick.order_depths,
            own_trades={},
            market_trades={},
            position=dict(positions),
            observations=None,
        )
        result = trader.run(state)
        orders_dict, _, _ = result

        for product, orders in orders_dict.items():
            if not orders:
                continue
            depth = tick.order_depths.get(product)
            if depth is None:
                continue
            gt = tick.gt_fills.get(product, [])
            pos = positions.get(product, 0)
            lim = position_limits.get(product, 0)
            fills, new_pos = _match_orders_for_product(
                product, orders, depth, gt, pos, lim, tick.timestamp
            )
            positions[product] = new_pos
            for f in fills:
                cash[product] = cash.get(product, 0.0) - f.price * f.qty
                all_fills.append(f)

    total = 0.0
    pnl_by_product: Dict[str, float] = {}
    for product in set(list(cash.keys()) + list(positions.keys())):
        c = cash.get(product, 0.0)
        pos = positions.get(product, 0)
        mtm = pos * final_mids.get(product, 0.0)
        pnl = c + mtm
        pnl_by_product[product] = pnl
        total += pnl

    return SimResult(
        fills=all_fills,
        pnl_by_product=pnl_by_product,
        position_by_product=positions,
        cash_by_product=cash,
        total_pnl=total,
    )
