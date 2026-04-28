import json
import math
from statistics import NormalDist

import numpy as np
from datamodel import Order, OrderDepth, TradingState


N = NormalDist()


class Trader:
    """523197 voucher engine plus Mark 14/Mark 38 liquidity replacement.

    The original 523197 trader made most of its PnL by shorting overpriced
    mid-strike VEV vouchers. HYDROGEL_PACK and VEV_4000 are handled separately
    here because the Round 4 Mark 14 analysis showed a repeatable spread-capture
    edge from replacing Mark 14's resting liquidity against Mark 38.
    """

    LIQUIDITY_PRODUCTS = {
        "HYDROGEL_PACK": {
            "position_limit": 200,
            "test_limit": 100,
            "min_edge": 5.0,
            "inventory_skew": 0.08,
            "inside_ticks": 2,
            "clip": 6,
        },
        "VEV_4000": {
            "position_limit": 300,
            "test_limit": 60,
            "min_edge": 7.0,
            "inventory_skew": 0.15,
            "inside_ticks": 1,
            "clip": 3,
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

    def liquidity_replacement_orders(self, product, od, position):
        cfg = self.LIQUIDITY_PRODUCTS[product]
        if not od.buy_orders or not od.sell_orders:
            return []

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)
        mid = (best_bid + best_ask) / 2
        inside_ticks = int(cfg["inside_ticks"])
        buy_price = best_bid + inside_ticks
        sell_price = best_ask - inside_ticks

        test_limit = min(int(cfg["test_limit"]), int(cfg["position_limit"]))
        clip = int(cfg["clip"])
        min_edge = float(cfg["min_edge"])
        inventory_skew = float(cfg["inventory_skew"])

        buy_capacity = test_limit - position
        sell_capacity = test_limit + position
        buy_required_edge = min_edge + max(position, 0) * inventory_skew
        sell_required_edge = min_edge + max(-position, 0) * inventory_skew

        orders = []
        if buy_capacity > 0 and buy_price < best_ask:
            buy_edge = mid - buy_price
            if buy_edge >= buy_required_edge:
                orders.append(Order(product, buy_price, min(clip, buy_capacity)))

        if sell_capacity > 0 and sell_price > best_bid:
            sell_edge = sell_price - mid
            if sell_edge >= sell_required_edge:
                orders.append(Order(product, sell_price, -min(clip, sell_capacity)))

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

        # Strategy Parameters
        ALPHA = 0.5
        MAX_SKEW = 4

        emas = td.get("emas", {})

        # 1. Process underlying VELVETFRUIT_EXTRACT first to use for vouchers.
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

        # Calculate implied vol proxy for options.
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

        # 2. Main loop for all products.
        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                continue

            pos = state.position.get(product, 0)

            if product in self.LIQUIDITY_PRODUCTS:
                orders = self.liquidity_replacement_orders(product, od, pos)
                if orders:
                    result[product] = orders
                continue

            best_bid = max(od.buy_orders)
            best_ask = min(od.sell_orders)
            mid = (best_bid + best_ask) / 2
            spread = best_ask - best_bid

            # EMA update for non-underlying products. Underlying was updated above.
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
