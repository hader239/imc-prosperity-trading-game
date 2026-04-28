import json
import math
from statistics import NormalDist

import numpy as np
from datamodel import Order, OrderDepth, TradingState


N = NormalDist()


class Trader:
    """523197 voucher engine plus an aggressive Mark 14 reversion module.

    Same shape as the moderate reversion variant, but with bigger caps,
    bigger favored-side clips, and a small directional take-out when
    the EMA deviation is large enough that the next mean-reversion
    move is more valuable than waiting for the next Mark 38 fill.
    Voucher logic is unchanged.
    """

    LIQUIDITY_PRODUCTS = {
        "HYDROGEL_PACK": {
            "position_limit": 200,
            "base_test_limit": 120,
            "max_test_limit": 200,
            "min_edge": 4.0,
            "inventory_skew": 0.05,
            "inside_ticks": 2,
            "base_clip": 8,
            "favored_clip": 18,
            "ema_alpha": 0.5,
            "deviation_step": 0.7,
            "take_out_threshold": 1.8,
            "take_out_clip": 8,
        },
        "VEV_4000": {
            "position_limit": 300,
            "base_test_limit": 80,
            "max_test_limit": 150,
            "min_edge": 6.0,
            "inventory_skew": 0.10,
            "inside_ticks": 1,
            "base_clip": 4,
            "favored_clip": 10,
            "ema_alpha": 0.5,
            "deviation_step": 1.2,
            "take_out_threshold": 2.5,
            "take_out_clip": 4,
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
        take_out_threshold = float(cfg["take_out_threshold"])
        take_out_clip = int(cfg["take_out_clip"])

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
            buy_clip = max(1, int(round(base_clip * (1 - 0.7 * magnitude))))
        if favor_buy:
            sell_clip = max(1, int(round(base_clip * (1 - 0.7 * magnitude))))

        buy_capacity = buy_test_limit - position
        sell_capacity = sell_test_limit + position
        buy_required_edge = min_edge + max(position, 0) * inventory_skew
        sell_required_edge = min_edge + max(-position, 0) * inventory_skew

        orders = []

        deviation_ticks = abs(deviation) / max(step, 1e-9)
        if deviation_ticks >= take_out_threshold:
            position_limit = int(cfg["position_limit"])
            if deviation > 0:
                take_capacity = position_limit - position
                if take_capacity > 0:
                    qty = min(take_out_clip, take_capacity, sum(-v for v in od.sell_orders.values()))
                    if qty > 0:
                        orders.append(Order(product, best_ask, qty))
                        buy_capacity = max(0, buy_capacity - qty)
            else:
                take_capacity = position_limit + position
                if take_capacity > 0:
                    qty = min(take_out_clip, take_capacity, sum(od.buy_orders.values()))
                    if qty > 0:
                        orders.append(Order(product, best_bid, -qty))
                        sell_capacity = max(0, sell_capacity - qty)

        if buy_capacity > 0 and buy_price < best_ask:
            buy_edge = mid - buy_price
            if buy_edge >= buy_required_edge:
                orders.append(Order(product, buy_price, min(buy_clip, buy_capacity)))

        if sell_capacity > 0 and sell_price > best_bid:
            sell_edge = sell_price - mid
            if sell_edge >= sell_required_edge:
                orders.append(Order(product, sell_price, -min(sell_clip, sell_capacity)))

        return orders

    def run(self, state: TradingState):
        result = {}
        conversions = 0
        td = {}

        try:
            if state.traderData:
                td = json.loads(state.traderData)
        except Exception:
            pass

        ALPHA = 0.5
        MAX_SKEW = 4

        emas = td.get("emas", {})

        u_mid = None
        u_ema = None
        if "VELVETFRUIT_EXTRACT" in state.order_depths:
            od = state.order_depths["VELVETFRUIT_EXTRACT"]
            if od.buy_orders and od.sell_orders:
                best_bid = max(od.buy_orders)
                best_ask = min(od.sell_orders)
                u_mid = (best_bid + best_ask) / 2

                prev_ema = emas.get("VELVETFRUIT_EXTRACT", u_mid)
                u_ema = ALPHA * u_mid + (1 - ALPHA) * prev_ema
                emas["VELVETFRUIT_EXTRACT"] = u_ema

        base_iv = 0.05
        options = {}
        if u_mid is not None:
            for symbol, od in state.order_depths.items():
                if ("VEV_" in symbol or "VOUCHER" in symbol) and od.buy_orders and od.sell_orders:
                    try:
                        parts = symbol.split("_")
                        strike = int(parts[-1])
                        mid = (max(od.buy_orders) + min(od.sell_orders)) / 2
                        options[symbol] = {"K": strike, "mid": mid}
                    except Exception:
                        pass

            if options:
                mids = [option["mid"] for option in options.values()]
                base_iv = np.median(mids) / u_mid

        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                continue

            pos = state.position.get(product, 0)

            if product in self.LIQUIDITY_PRODUCTS:
                cfg = self.LIQUIDITY_PRODUCTS[product]
                best_bid_l = max(od.buy_orders)
                best_ask_l = min(od.sell_orders)
                mid_l = (best_bid_l + best_ask_l) / 2
                prev_ema_l = emas.get(product, mid_l)
                ema_l = float(cfg["ema_alpha"]) * mid_l + (1 - float(cfg["ema_alpha"])) * prev_ema_l
                emas[product] = ema_l
                orders = self.liquidity_reversion_orders(product, od, pos, ema_l)
                if orders:
                    result[product] = orders
                continue

            best_bid = max(od.buy_orders)
            best_ask = min(od.sell_orders)
            mid = (best_bid + best_ask) / 2
            spread = best_ask - best_bid

            if product != "VELVETFRUIT_EXTRACT":
                prev_ema = emas.get(product, mid)
                ema = ALPHA * mid + (1 - ALPHA) * prev_ema
                emas[product] = ema
            else:
                ema = emas["VELVETFRUIT_EXTRACT"]

            limit = self.LIMITS.get(
                product, 300 if ("VEV_" in product or "VOUCHER" in product) else 0
            )
            if limit == 0:
                continue

            if ("VEV_" in product or "VOUCHER" in product) and u_ema is not None and product in options:
                strike = options[product]["K"]
                theo, _ = self.bs(u_ema, strike, 1 / 365, base_iv)
                fair = theo
            else:
                fair = ema

            skew = (pos / limit) * MAX_SKEW
            adjusted_fair = fair - skew

            edge = max(1, int(spread * 0.25))
            dir_threshold = max(2, int(spread * 0.40))

            buy_price = int(math.floor(adjusted_fair - edge))
            sell_price = int(math.ceil(adjusted_fair + edge))

            buy_price = min(buy_price, best_ask - 1)
            sell_price = max(sell_price, best_bid + 1)

            orders = []

            ask_vol_taken = 0
            for ask_px, ask_vol in sorted(od.sell_orders.items()):
                if ask_px <= adjusted_fair - dir_threshold:
                    take_vol = min(-ask_vol, limit - pos - ask_vol_taken)
                    if take_vol > 0:
                        orders.append(Order(product, ask_px, take_vol))
                        ask_vol_taken += take_vol

            bid_vol_taken = 0
            for bid_px, bid_vol in sorted(od.buy_orders.items(), reverse=True):
                if bid_px >= adjusted_fair + dir_threshold:
                    take_vol = min(bid_vol, pos + limit - bid_vol_taken)
                    if take_vol > 0:
                        orders.append(Order(product, bid_px, -take_vol))
                        bid_vol_taken += take_vol

            rem_buy_cap = limit - pos - ask_vol_taken
            rem_sell_cap = limit + pos - bid_vol_taken

            if rem_buy_cap > 0:
                orders.append(Order(product, buy_price, rem_buy_cap))
            if rem_sell_cap > 0:
                orders.append(Order(product, sell_price, -rem_sell_cap))

            result[product] = orders

        td["emas"] = emas
        return result, conversions, json.dumps(td)
