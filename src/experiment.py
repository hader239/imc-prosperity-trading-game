"""
Parametric trader + experiment harness for searching strategy space.

All traders share the same EMERALDS core (take + full-capacity passive at
best_bid+1 / best_ask-1). TOMATOES is the lever we sweep.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Dict, List

sys.path.insert(0, "src")

from datamodel import Order, OrderDepth, TradingState
from simulator import load_reference, simulate


# ---------------------------------------------------------------------------
# Parametric trader
# ---------------------------------------------------------------------------


@dataclass
class TomatoParams:
    take_enabled: bool = True         # take cheap asks / rich bids vs wall_mid
    take_position_cap: int = 80       # symmetric cap on take-induced position
    take_buy_cap: int = None          # asymmetric buy-side cap (override symmetric)
    take_sell_cap: int = None         # asymmetric sell-side cap (override symmetric)
    take_min_edge: float = 0.0        # require edge >= this before taking
    quote_enabled: bool = True        # post passive best_bid+1 / best_ask-1
    quote_size: int = 20              # max size per passive side per tick
    quote_min_edge: float = 0.0       # require edge vs wall_mid > this on each side
    skip_narrow_quotes: bool = False  # don't post passive on narrow-state ticks
    narrow_spread_threshold: int = 9  # "narrow" = spread <= this
    skew_size_by_position: bool = False  # larger quote on side that reduces |pos|
    skew_factor: float = 1.0          # how aggressively to skew


@dataclass
class EmeraldParams:
    take_enabled: bool = True
    quote_offset: int = 1             # best_bid+offset, best_ask-offset


class ParamTrader:
    POSITION_LIMIT = {"EMERALDS": 80, "TOMATOES": 80}

    def __init__(self, tomato: TomatoParams = None, emerald: EmeraldParams = None):
        self.tomato = tomato or TomatoParams()
        self.emerald = emerald or EmeraldParams()

    def run(self, state):
        out = {}
        if "EMERALDS" in state.order_depths:
            out["EMERALDS"] = self._trade_emeralds(
                state.order_depths["EMERALDS"], state.position.get("EMERALDS", 0)
            )
        if "TOMATOES" in state.order_depths:
            out["TOMATOES"] = self._trade_tomatoes(
                state.order_depths["TOMATOES"], state.position.get("TOMATOES", 0)
            )
        return out, 0, ""

    def _wall_mid(self, od: OrderDepth) -> float:
        wb = max(od.buy_orders.items(), key=lambda kv: kv[1])[0]
        wa = max(od.sell_orders.items(), key=lambda kv: abs(kv[1]))[0]
        return (wb + wa) / 2

    # ------------------------------------------------------------------
    def _trade_emeralds(self, od, position):
        orders: List[Order] = []
        fair = 10000
        limit = self.POSITION_LIMIT["EMERALDS"]
        off = self.emerald.quote_offset

        if self.emerald.take_enabled:
            for ap in sorted(od.sell_orders.keys()):
                if ap >= fair: break
                avail = -od.sell_orders[ap]
                room = limit - position
                if room <= 0: break
                q = min(avail, room)
                orders.append(Order("EMERALDS", ap, q))
                position += q
            for bp in sorted(od.buy_orders.keys(), reverse=True):
                if bp <= fair: break
                avail = od.buy_orders[bp]
                room = limit + position
                if room <= 0: break
                q = min(avail, room)
                orders.append(Order("EMERALDS", bp, -q))
                position -= q

        buy_cap = limit - position
        sell_cap = limit + position
        best_ask = min(od.sell_orders.keys())
        best_bid = max(od.buy_orders.keys())

        my_bid = max(best_bid + 1, fair - off)  # don't post worse than fair-off
        my_ask = min(best_ask - 1, fair + off)

        if buy_cap > 0 and my_bid < fair:
            orders.append(Order("EMERALDS", my_bid, buy_cap))
        if sell_cap > 0 and my_ask > fair:
            orders.append(Order("EMERALDS", my_ask, -sell_cap))
        return orders

    # ------------------------------------------------------------------
    def _trade_tomatoes(self, od, position):
        orders: List[Order] = []
        limit = self.POSITION_LIMIT["TOMATOES"]
        p = self.tomato

        if not od.buy_orders or not od.sell_orders:
            return orders

        wm = self._wall_mid(od)

        # --- Take layer ---
        buy_cap_limit = p.take_buy_cap if p.take_buy_cap is not None else p.take_position_cap
        sell_cap_limit = p.take_sell_cap if p.take_sell_cap is not None else p.take_position_cap
        if p.take_enabled:
            for ap in sorted(od.sell_orders.keys()):
                edge = wm - ap
                if edge <= p.take_min_edge: break
                avail = -od.sell_orders[ap]
                room = limit - position
                if room <= 0: break
                cap_room = buy_cap_limit - position
                if cap_room <= 0: break
                room = min(room, cap_room)
                q = min(avail, room)
                if q <= 0: break
                orders.append(Order("TOMATOES", ap, q))
                position += q
            for bp in sorted(od.buy_orders.keys(), reverse=True):
                edge = bp - wm
                if edge <= p.take_min_edge: break
                avail = od.buy_orders[bp]
                room = limit + position
                if room <= 0: break
                cap_room = sell_cap_limit + position
                if cap_room <= 0: break
                room = min(room, cap_room)
                q = min(avail, room)
                if q <= 0: break
                orders.append(Order("TOMATOES", bp, -q))
                position -= q

        # --- Passive quotes ---
        if not p.quote_enabled:
            return orders

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        spread = best_ask - best_bid

        if spread <= 2:
            return orders  # can't make a passive quote that fits

        if p.skip_narrow_quotes and spread <= p.narrow_spread_threshold:
            return orders  # opt-out of narrow-state passive quoting

        my_bid = best_bid + 1
        my_ask = best_ask - 1

        buy_cap = limit - position
        sell_cap = limit + position

        bid_size = p.quote_size
        ask_size = p.quote_size
        if p.skew_size_by_position and position != 0:
            # Larger on the side that reduces |position|
            if position > 0:
                ask_size = int(p.quote_size * p.skew_factor)
            else:
                bid_size = int(p.quote_size * p.skew_factor)

        bid_edge = wm - my_bid
        ask_edge = my_ask - wm
        if buy_cap > 0 and bid_edge > p.quote_min_edge:
            orders.append(Order("TOMATOES", my_bid, min(bid_size, buy_cap)))
        if sell_cap > 0 and ask_edge > p.quote_min_edge:
            orders.append(Order("TOMATOES", my_ask, -min(ask_size, sell_cap)))
        return orders


# ---------------------------------------------------------------------------
# Experiment runner
# ---------------------------------------------------------------------------


def run_experiment(label: str, trader, ticks, final_mids, verbose=False):
    res = simulate(
        trader=trader,
        tick_states=ticks,
        final_mids=final_mids,
        position_limits={"EMERALDS": 80, "TOMATOES": 80},
    )
    tom = res.pnl_by_product.get("TOMATOES", 0)
    eme = res.pnl_by_product.get("EMERALDS", 0)
    tom_pos = res.position_by_product.get("TOMATOES", 0)
    eme_pos = res.position_by_product.get("EMERALDS", 0)
    n_tom_take = sum(1 for f in res.fills if f.product == "TOMATOES" and f.kind == "take")
    n_tom_pass = sum(1 for f in res.fills if f.product == "TOMATOES" and f.kind == "passive")
    print(
        f"  {label:<50s}  TOT={res.total_pnl:+8.2f}  "
        f"EME={eme:+7.1f}  TOM={tom:+7.1f}  "
        f"end_tom={tom_pos:+3d}  "
        f"take/pass={n_tom_take:>2d}/{n_tom_pass:>2d}"
    )
    return res
