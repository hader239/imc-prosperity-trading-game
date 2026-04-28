"""HYDROGEL_PACK active market-maker, v1 (tests 1+2+3+4).

Same passive structure as `src/hydrogel_passive_v2.py`, plus an
imbalance-triggered taker (test 4). When the public book signals strong
short-term direction for two consecutive ticks, lift one ask level (or
hit one bid level) for a small clip. Auto-flattening is implicit: the
passive market-maker absorbs the directional inventory back to neutral.

Trigger:
- |combo_sig| >= 1.0 for last 2 ticks, OR
- |imb1| >= 0.5 for last 2 ticks
- and at least 100 ticks since last taker fill
- and the directional position cap is not exceeded.

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

    TAKER = {
        "combo_threshold": 1.0,
        "imb_threshold": 0.5,
        "consecutive_ticks": 2,
        "cooldown_ticks": 100,
        "clip": 3,
        "max_position": 80,
        "history_size": 4,
    }

    def _book_signals(self, od: OrderDepth):
        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)
        mid = (best_bid + best_ask) / 2

        bv1 = od.buy_orders[best_bid]
        av1 = -od.sell_orders[best_ask]
        denom = bv1 + av1
        microprice = (
            (best_bid * av1 + best_ask * bv1) / denom if denom > 0 else mid
        )
        imb1 = ((bv1 - av1) / denom) if denom > 0 else 0.0
        mp_dev = microprice - mid

        bid_levels = sorted(od.buy_orders.items(), reverse=True)
        ask_levels = sorted(od.sell_orders.items())
        bid_wall_px, _ = max(bid_levels, key=lambda kv: kv[1])
        ask_wall_px, _ = max(ask_levels, key=lambda kv: -kv[1])
        wall_mid = (bid_wall_px + ask_wall_px) / 2
        wall_dev = wall_mid - mid

        combo_sig = 0.5 * mp_dev + 0.5 * wall_dev

        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": mid,
            "bv1": bv1,
            "av1": av1,
            "microprice": microprice,
            "imb1": imb1,
            "mp_dev": mp_dev,
            "wall_dev": wall_dev,
            "combo_sig": combo_sig,
        }

    def hydrogel_passive_orders(
        self,
        sig: Dict[str, float],
        position: int,
        rolling_mean: Optional[float],
        passive_buy_taken: int,
        passive_sell_taken: int,
    ) -> List[Order]:
        cfg = self.HYDROGEL
        best_bid = sig["best_bid"]
        best_ask = sig["best_ask"]
        if best_ask <= best_bid + 1:
            return []

        mid = sig["mid"]
        mp_dev = sig["mp_dev"]
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

        buy_capacity = buy_limit - position - passive_buy_taken
        sell_capacity = sell_limit + position - passive_sell_taken
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

    def hydrogel_taker_orders(
        self,
        sig: Dict[str, float],
        od: OrderDepth,
        position: int,
        trader_data: Dict[str, Any],
        timestamp: int,
        passive_buy_taken: int,
        passive_sell_taken: int,
    ) -> List[Order]:
        tcfg = self.TAKER
        cfg = self.HYDROGEL

        combo_hist = trader_data.get("combo_hist", [])
        imb_hist = trader_data.get("imb_hist", [])
        if not isinstance(combo_hist, list):
            combo_hist = []
        if not isinstance(imb_hist, list):
            imb_hist = []

        combo_hist.append(sig["combo_sig"])
        imb_hist.append(sig["imb1"])
        max_hist = int(tcfg["history_size"])
        combo_hist = combo_hist[-max_hist:]
        imb_hist = imb_hist[-max_hist:]
        trader_data["combo_hist"] = combo_hist
        trader_data["imb_hist"] = imb_hist

        last_take_time = trader_data.get("last_take_time", -10**9)
        if timestamp - last_take_time < int(tcfg["cooldown_ticks"]):
            return []

        consecutive = int(tcfg["consecutive_ticks"])
        if len(combo_hist) < consecutive:
            return []

        combo_thr = float(tcfg["combo_threshold"])
        imb_thr = float(tcfg["imb_threshold"])
        last_combo = combo_hist[-consecutive:]
        last_imb = imb_hist[-consecutive:]
        long_signal = (
            all(c >= combo_thr for c in last_combo)
            or all(i >= imb_thr for i in last_imb)
        )
        short_signal = (
            all(c <= -combo_thr for c in last_combo)
            or all(i <= -imb_thr for i in last_imb)
        )

        clip = int(tcfg["clip"])
        max_pos = min(int(tcfg["max_position"]), int(cfg["position_limit"]))
        orders: List[Order] = []

        best_bid = sig["best_bid"]
        best_ask = sig["best_ask"]

        if long_signal and position + passive_buy_taken < max_pos:
            available = -od.sell_orders.get(best_ask, 0)
            qty = min(clip, max_pos - position - passive_buy_taken, available)
            if qty > 0:
                orders.append(Order(self.PRODUCT, int(best_ask), qty))
                trader_data["last_take_time"] = timestamp
        elif short_signal and position - passive_sell_taken > -max_pos:
            available = od.buy_orders.get(best_bid, 0)
            qty = min(clip, max_pos + position - passive_sell_taken, available)
            if qty > 0:
                orders.append(Order(self.PRODUCT, int(best_bid), -qty))
                trader_data["last_take_time"] = timestamp

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
            sig = self._book_signals(od)
            mid = sig["mid"]
            rolling_mean = self.hydrogel_rolling_mean(trader_data, mid)

            position = state.position.get(self.PRODUCT, 0)
            passive_buy_taken = 0
            passive_sell_taken = 0

            taker_orders = self.hydrogel_taker_orders(
                sig=sig,
                od=od,
                position=position,
                trader_data=trader_data,
                timestamp=state.timestamp,
                passive_buy_taken=passive_buy_taken,
                passive_sell_taken=passive_sell_taken,
            )
            for o in taker_orders:
                if o.quantity > 0:
                    passive_buy_taken += o.quantity
                else:
                    passive_sell_taken += -o.quantity

            passive_orders = self.hydrogel_passive_orders(
                sig=sig,
                position=position,
                rolling_mean=rolling_mean,
                passive_buy_taken=passive_buy_taken,
                passive_sell_taken=passive_sell_taken,
            )

            orders = taker_orders + passive_orders
            if orders:
                result[self.PRODUCT] = orders

        return result, conversions, json.dumps(trader_data, separators=(",", ":"))
