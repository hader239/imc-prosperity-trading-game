"""HYDROGEL_PACK passive market-maker, v2 (tests 1+2+3).

Builds on the strategy 6 base in `src/hydrogel_specialist.py` with:

1. Looser rolling-mean reversion knobs so the inventory carry actually
   triggers more often (lower threshold and step, higher base cap).
2. A third resting level at the top of the public book (k=0), sharing
   queue with the original HYDROGEL liquidity provider for additional
   fills the v1 specialist could never get.
3. Microprice / top-of-book imbalance skew on the quote center: when the
   weighted micro-mid leans, both quotes shift by 1 tick toward that
   side, capped together with the rolling-mean shift.

Market-data only. No counterparty names referenced.
"""

import json
from typing import Any, Dict, List, Optional

from datamodel import Order, OrderDepth, TradingState


class Trader:

    PRODUCT = "HYDROGEL_PACK"

    HYDROGEL = {
        "position_limit": 200,
        "base_inventory_cap": 80,
        "reversion_inventory_cap": 160,
        "primary_clip": 8,
        "deeper_clip": 3,
        "deeper_offset": 3,
        "top_clip": 4,
        "skew_unit": 25,
        "rolling_window": 1500,
        "rolling_warmup": 300,
        "reversion_threshold": 3.0,
        "reversion_step": 4.0,
        "reversion_shift_clip": 2,
        "microprice_threshold": 0.25,
        "microprice_shift": 1,
        "min_edge": 2.0,
    }

    def hydrogel_orders(
        self,
        od: OrderDepth,
        position: int,
        rolling_mean: Optional[float],
    ) -> List[Order]:
        cfg = self.HYDROGEL
        if not od.buy_orders or not od.sell_orders:
            return []

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)
        if best_ask <= best_bid + 1:
            return []

        mid = (best_bid + best_ask) / 2

        bv1 = od.buy_orders[best_bid]
        av1 = -od.sell_orders[best_ask]
        denom = bv1 + av1
        microprice = (
            (best_bid * av1 + best_ask * bv1) / denom if denom > 0 else mid
        )
        mp_dev = microprice - mid
        mp_thr = float(cfg["microprice_threshold"])
        mp_clip = int(cfg["microprice_shift"])
        if mp_dev >= mp_thr:
            mp_shift = mp_clip
        elif mp_dev <= -mp_thr:
            mp_shift = -mp_clip
        else:
            mp_shift = 0

        deviation = (rolling_mean - mid) if rolling_mean is not None else 0.0
        threshold = float(cfg["reversion_threshold"])
        step = float(cfg["reversion_step"])
        shift_clip = int(cfg["reversion_shift_clip"])
        favor_buy = deviation >= threshold
        favor_sell = deviation <= -threshold
        rev_shift = (
            int(round(deviation / step)) if rolling_mean is not None else 0
        )
        rev_shift = max(-shift_clip, min(shift_clip, rev_shift))

        signal_shift = max(
            -shift_clip,
            min(shift_clip, mp_shift + rev_shift),
        )

        skew_int = int(round(position / float(cfg["skew_unit"])))
        buy_price = best_bid + 1 + signal_shift - skew_int
        sell_price = best_ask - 1 + signal_shift - skew_int

        buy_price = min(buy_price, best_ask - 1)
        sell_price = max(sell_price, best_bid + 1)
        if buy_price >= sell_price:
            sell_price = buy_price + 1

        deeper_off = int(cfg["deeper_offset"])
        deeper_buy = best_bid + deeper_off - skew_int
        deeper_sell = best_ask - deeper_off - skew_int
        deeper_buy = min(deeper_buy, buy_price - 1)
        deeper_sell = max(deeper_sell, sell_price + 1)

        position_limit = int(cfg["position_limit"])
        base_cap = min(int(cfg["base_inventory_cap"]), position_limit)
        reversion_cap = min(int(cfg["reversion_inventory_cap"]), position_limit)
        buy_limit = reversion_cap if favor_buy else base_cap
        sell_limit = reversion_cap if favor_sell else base_cap

        buy_capacity = buy_limit - position
        sell_capacity = sell_limit + position
        primary_clip = int(cfg["primary_clip"])
        deeper_clip = int(cfg["deeper_clip"])
        top_clip = int(cfg["top_clip"])
        min_edge = float(cfg["min_edge"])

        orders: List[Order] = []

        if (
            buy_capacity > 0
            and deeper_buy < best_ask
            and (mid - deeper_buy) >= min_edge
        ):
            qty = min(deeper_clip, buy_capacity)
            if qty > 0:
                orders.append(Order(self.PRODUCT, int(deeper_buy), qty))
                buy_capacity -= qty

        if (
            buy_capacity > 0
            and buy_price < best_ask
            and (mid - buy_price) >= min_edge
        ):
            qty = min(primary_clip, buy_capacity)
            if qty > 0:
                orders.append(Order(self.PRODUCT, int(buy_price), qty))
                buy_capacity -= qty

        if buy_capacity > 0 and (mid - best_bid) >= min_edge:
            qty = min(top_clip, buy_capacity)
            if qty > 0:
                orders.append(Order(self.PRODUCT, int(best_bid), qty))
                buy_capacity -= qty

        if (
            sell_capacity > 0
            and deeper_sell > best_bid
            and (deeper_sell - mid) >= min_edge
        ):
            qty = min(deeper_clip, sell_capacity)
            if qty > 0:
                orders.append(Order(self.PRODUCT, int(deeper_sell), -qty))
                sell_capacity -= qty

        if (
            sell_capacity > 0
            and sell_price > best_bid
            and (sell_price - mid) >= min_edge
        ):
            qty = min(primary_clip, sell_capacity)
            if qty > 0:
                orders.append(Order(self.PRODUCT, int(sell_price), -qty))
                sell_capacity -= qty

        if sell_capacity > 0 and (best_ask - mid) >= min_edge:
            qty = min(top_clip, sell_capacity)
            if qty > 0:
                orders.append(Order(self.PRODUCT, int(best_ask), -qty))
                sell_capacity -= qty

        return orders

    def hydrogel_rolling_mean(
        self, trader_data: Dict[str, Any], mid: float
    ) -> Optional[float]:
        cfg = self.HYDROGEL
        window = int(cfg["rolling_window"])
        warmup = int(cfg["rolling_warmup"])

        mids = trader_data.get("hydrogel_mids", [])
        if not isinstance(mids, list):
            mids = []

        rolling_mean: Optional[float] = None
        if len(mids) >= warmup:
            rolling_mean = sum(mids) / (2.0 * len(mids))

        mids.append(int(round(mid * 2)))
        if len(mids) > window:
            mids = mids[-window:]
        trader_data["hydrogel_mids"] = mids

        return rolling_mean

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        conversions = 0
        trader_data: Dict[str, Any] = {}
        try:
            if state.traderData:
                loaded = json.loads(state.traderData)
                if isinstance(loaded, dict):
                    trader_data = loaded
        except Exception:
            trader_data = {}

        od = state.order_depths.get(self.PRODUCT)
        if od is not None and od.buy_orders and od.sell_orders:
            best_bid = max(od.buy_orders)
            best_ask = min(od.sell_orders)
            mid = (best_bid + best_ask) / 2
            rolling_mean = self.hydrogel_rolling_mean(trader_data, mid)
            orders = self.hydrogel_orders(
                od,
                state.position.get(self.PRODUCT, 0),
                rolling_mean,
            )
            if orders:
                result[self.PRODUCT] = orders

        return result, conversions, json.dumps(trader_data, separators=(",", ":"))
