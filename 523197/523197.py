import math
import numpy as np
import json
from datamodel import OrderDepth, TradingState, Order
from statistics import NormalDist

N = NormalDist()

class Trader:
    
    def bs(self, S, K, T, sigma):
        if sigma <= 0:
            return 0, 0
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        delta = N.cdf(d1)
        price = S * delta - K * N.cdf(d1 - sigma * math.sqrt(T))
        return price, delta

    def run(self, state: TradingState):
        result = {}
        conversions = 0
        td = {}
        
        try:
            if state.traderData:
                td = json.loads(state.traderData)
        except:
            pass

        # Strategy Parameters
        ALPHA = 0.5
        MAX_SKEW = 4

        LIMITS = {
            "HYDROGEL_PACK": 200,
            "VELVETFRUIT_EXTRACT": 200
        }
        
        emas = td.get("emas", {})
        
        # 1. Process Underlying VELVETFRUIT_EXTRACT first to use for vouchers
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

        # Calculate implied vol proxy for options
        base_iv = 0.05 # default fallback
        options = {}
        if u_mid is not None:
            for s, od in state.order_depths.items():
                if ("VEV_" in s or "VOUCHER" in s) and od.buy_orders and od.sell_orders:
                    try:
                        # Extract strike (e.g., from VEV_700)
                        parts = s.split("_")
                        K = int(parts[-1])
                        mid = (max(od.buy_orders) + min(od.sell_orders)) / 2
                        options[s] = {"K": K, "mid": mid}
                    except:
                        pass
            
            if options:
                # Same proxy logic as exampleTrader.py: median(price) / S
                mids = [o["mid"] for o in options.values()]
                base_iv = np.median(mids) / u_mid
                
        # 2. Main Loop for all products
        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                continue
                
            best_bid = max(od.buy_orders)
            best_ask = min(od.sell_orders)
            mid = (best_bid + best_ask) / 2
            spread = best_ask - best_bid
            
            # EMA Update for non-underlying products (underlying was already updated)
            if product != "VELVETFRUIT_EXTRACT":
                # For vouchers, we don't strictly need their own EMA anymore, but we track it anyway
                prev_ema = emas.get(product, mid)
                ema = ALPHA * mid + (1 - ALPHA) * prev_ema
                emas[product] = ema
            else:
                ema = emas["VELVETFRUIT_EXTRACT"]

            # Limit setup
            limit = LIMITS.get(product, 300 if ("VEV_" in product or "VOUCHER" in product) else 0)
            if limit == 0:
                continue # Unknown product, don't trade

            pos = state.position.get(product, 0)
            
            # Fair Value Calculation
            if ("VEV_" in product or "VOUCHER" in product) and u_ema is not None and product in options:
                # Use pure Black-Scholes theoretical value based on the underlying's EMA
                K = options[product]["K"]
                theo, _ = self.bs(u_ema, K, 1/365, base_iv)
                fair = theo
            else:
                # Standard EMA mean reversion
                fair = ema
                
            # Skew Calculation
            skew = (pos / limit) * MAX_SKEW
            adjusted_fair = fair - skew
            
            # Dynamic Edge & Threshold calculation based on market spread
            # Capture 25% of spread as edge, require 40% of spread to cross directionally
            edge = max(1, int(spread * 0.25))
            dir_threshold = max(2, int(spread * 0.40))
            
            buy_price = int(math.floor(adjusted_fair - edge))
            sell_price = int(math.ceil(adjusted_fair + edge))
            
            # Ensure we don't cross the spread negatively against ourselves
            buy_price = min(buy_price, best_ask - 1)
            sell_price = max(sell_price, best_bid + 1)

            orders = []
            
            # Directional trading (taking liquidity)
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
                        
            # Market making (providing liquidity)
            rem_buy_cap = limit - pos - ask_vol_taken
            rem_sell_cap = limit + pos - bid_vol_taken
            
            if rem_buy_cap > 0:
                orders.append(Order(product, buy_price, rem_buy_cap))
            if rem_sell_cap > 0:
                orders.append(Order(product, sell_price, -rem_sell_cap))

            result[product] = orders

        td["emas"] = emas
        return result, conversions, json.dumps(td)