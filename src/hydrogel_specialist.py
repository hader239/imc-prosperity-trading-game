import json
import math
from statistics import NormalDist

import numpy as np
from datamodel import Order, OrderDepth, TradingState


N = NormalDist()


class Trader:
    """523197 voucher engine plus a HYDROGEL_PACK specialist module.

    HYDROGEL_PACK uses a microprice/wall-mid skewed, multi-level passive
    maker that always quotes both sides. VEV_4000 keeps the moderate
    Mark 14 reversion module from trader_523197_mark14_reversion. The
    voucher engine and VELVETFRUIT_EXTRACT logic are unchanged from
    523197.
    """

    HYDROGEL = {
        "position_limit": 200,
        "base_inventory_cap": 50,
        "reversion_inventory_cap": 140,
        "primary_clip": 8,
        "deeper_clip": 3,
        "deeper_offset": 3,
        "skew_unit": 25,
        "rolling_window": 1500,
        "rolling_warmup": 300,
        "reversion_threshold": 8.0,
        "reversion_step": 12.0,
        "reversion_shift_clip": 2,
        "min_edge": 3.0,
    }

    LIQUIDITY_PRODUCTS = {
        "VEV_4000": {
            "position_limit": 300,
            "base_test_limit": 60,
            "max_test_limit": 90,
            "min_edge": 7.0,
            "inventory_skew": 0.15,
            "inside_ticks": 1,
            "base_clip": 3,
            "favored_clip": 5,
            "ema_alpha": 0.5,
            "deviation_step": 1.5,
        },
    }

    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
    }

    def bs(self, S, K, T, sigma):
        if sigma <= 0:
            return 0, 0
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (
            sigma * math.sqrt(T)
        )
        delta = N.cdf(d1)
        price = S * delta - K * N.cdf(d1 - sigma * math.sqrt(T))
        return price, delta

    def liquidity_reversion_orders(self, product, od, position, ema):
        cfg = self.LIQUIDITY_PRODUCTS[product]
        if not od.buy_orders or not od.sell_orders:
            return []

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)
        mid = (best_bid + best_ask) / 2
        inside_ticks = int(cfg["inside_ticks"])
        buy_price = best_bid + inside_ticks
        sell_price = best_ask - inside_ticks

        base_test_limit = min(int(cfg["base_test_limit"]), int(cfg["position_limit"]))
        max_test_limit = min(int(cfg["max_test_limit"]), int(cfg["position_limit"]))
        base_clip = int(cfg["base_clip"])
        favored_clip = int(cfg["favored_clip"])
        min_edge = float(cfg["min_edge"])
        inventory_skew = float(cfg["inventory_skew"])
        step = float(cfg["deviation_step"])

        deviation = ema - mid if ema is not None else 0.0
        bias_units = max(min(deviation / step, 1.0), -1.0)
        favor_buy = bias_units > 0
        favor_sell = bias_units < 0
        magnitude = abs(bias_units)

        buy_test_limit = base_test_limit + int(round((max_test_limit - base_test_limit) * (magnitude if favor_buy else 0)))
        sell_test_limit = base_test_limit + int(round((max_test_limit - base_test_limit) * (magnitude if favor_sell else 0)))

        buy_clip = base_clip + int(round((favored_clip - base_clip) * (magnitude if favor_buy else 0)))
        sell_clip = base_clip + int(round((favored_clip - base_clip) * (magnitude if favor_sell else 0)))

        if favor_sell:
            buy_clip = max(1, int(round(base_clip * (1 - 0.5 * magnitude))))
        if favor_buy:
            sell_clip = max(1, int(round(base_clip * (1 - 0.5 * magnitude))))

        buy_capacity = buy_test_limit - position
        sell_capacity = sell_test_limit + position
        buy_required_edge = min_edge + max(position, 0) * inventory_skew
        sell_required_edge = min_edge + max(-position, 0) * inventory_skew

        orders = []
        if buy_capacity > 0 and buy_price < best_ask:
            buy_edge = mid - buy_price
            if buy_edge >= buy_required_edge:
                orders.append(Order(product, buy_price, min(buy_clip, buy_capacity)))

        if sell_capacity > 0 and sell_price > best_bid:
            sell_edge = sell_price - mid
            if sell_edge >= sell_required_edge:
                orders.append(Order(product, sell_price, -min(sell_clip, sell_capacity)))

        return orders

    def hydrogel_orders(self, od, position, rolling_mean):
        cfg = self.HYDROGEL
        if not od.buy_orders or not od.sell_orders:
            return []

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)
        if best_ask <= best_bid + 1:
            return []

        mid = (best_bid + best_ask) / 2

        deviation = rolling_mean - mid if rolling_mean is not None else 0.0
        threshold = float(cfg["reversion_threshold"])
        step = float(cfg["reversion_step"])
        shift_clip = int(cfg["reversion_shift_clip"])
        favor_buy = deviation >= threshold
        favor_sell = deviation <= -threshold

        signal_shift = int(round(deviation / step)) if rolling_mean is not None else 0
        signal_shift = max(-shift_clip, min(shift_clip, signal_shift))

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
        min_edge = float(cfg["min_edge"])

        orders = []

        if buy_capacity > 0 and buy_price < best_ask and (mid - buy_price) >= min_edge:
            qty = min(primary_clip, buy_capacity)
            if qty > 0:
                orders.append(Order("HYDROGEL_PACK", buy_price, qty))
                buy_capacity -= qty

        if sell_capacity > 0 and sell_price > best_bid and (sell_price - mid) >= min_edge:
            qty = min(primary_clip, sell_capacity)
            if qty > 0:
                orders.append(Order("HYDROGEL_PACK", sell_price, -qty))
                sell_capacity -= qty

        if buy_capacity > 0 and deeper_buy < best_ask and (mid - deeper_buy) >= min_edge + deeper_off:
            qty = min(deeper_clip, buy_capacity)
            if qty > 0:
                orders.append(Order("HYDROGEL_PACK", deeper_buy, qty))

        if sell_capacity > 0 and deeper_sell > best_bid and (deeper_sell - mid) >= min_edge + deeper_off:
            qty = min(deeper_clip, sell_capacity)
            if qty > 0:
                orders.append(Order("HYDROGEL_PACK", deeper_sell, -qty))

        return orders

    def hydrogel_rolling_mean(self, trader_data, mid):
        cfg = self.HYDROGEL
        window = int(cfg["rolling_window"])
        warmup = int(cfg["rolling_warmup"])

        mids = trader_data.get("hydrogel_mids", [])
        if not isinstance(mids, list):
            mids = []

        rolling_mean = None
        if len(mids) >= warmup:
            rolling_mean = sum(mids) / (2.0 * len(mids))

        mids.append(int(round(mid * 2)))
        if len(mids) > window:
            mids = mids[-window:]
        trader_data["hydrogel_mids"] = mids

        return rolling_mean

    def run(self, state: TradingState):
        result = {}
        conversions = 0
        trader_data = {}
        try:
            if state.traderData:
                loaded = json.loads(state.traderData)
                if isinstance(loaded, dict):
                    trader_data = loaded
        except Exception:
            trader_data = {}

        product = "HYDROGEL_PACK"
        od = state.order_depths.get(product)
        if od is not None and od.buy_orders and od.sell_orders:
            best_bid = max(od.buy_orders)
            best_ask = min(od.sell_orders)
            mid = (best_bid + best_ask) / 2
            rolling_mean = self.hydrogel_rolling_mean(trader_data, mid)
            orders = self.hydrogel_orders(
                od,
                state.position.get(product, 0),
                rolling_mean,
            )
            if orders:
                result[product] = orders

        return result, conversions, json.dumps(trader_data, separators=(",", ":"))
