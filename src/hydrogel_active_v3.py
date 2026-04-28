"""HYDROGEL_PACK active market-maker, v3.

Same as `src/hydrogel_active_v2.py` plus an explicit aggressive-join
probe layer (strategy 1, empirical test): when the unified bias score is
strong (|bias| >= 1), an additional resting quote is placed deep inside
the spread at `best_bid + join_offset` (or `best_ask - join_offset`).

Why this is in v3 and not v2:
- The historical data shows zero trades at mid+/-1, but that only proves
  that no historical bot QUOTED there. It does NOT prove that bots would
  not TAKE if we offered there. The Prosperity simulator allows bots to
  react to our outstanding quotes.
- The only way to find out is to put real orders inside the spread and
  see if anyone fills them.
- Per-fill PnL at the join layer is much smaller (we sacrifice ~6 ticks
  of edge per unit), so the strategy only pays off if the join layer
  attracts MORE fills than the conservative passive layers.

Diff vs active_v2:
- New `JOIN` config block.
- Join layer fires on |bias| >= 1 with clip 6 at offset 5 (so ~3 ticks
  of edge for spread 16). On |bias| >= 2 we tighten to offset 7 (1 tick
  of edge) for an even more aggressive volume probe.
- Join layer respects the same inventory caps as the rest of v2.

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
        "skew_unit": 25,
        "rolling_window": 1500,
        "rolling_warmup": 200,
        "reversion_threshold": 5.0,
        "reversion_threshold_strong": 10.0,
        "reversion_step": 4.0,
        "reversion_shift_clip": 2,
        "microprice_threshold": 0.25,
        "microprice_shift": 1,
        "min_edge": 2.0,
        "tick_shock_window": 3,
        "tick_shock_threshold": 5.0,
        "spread_narrow": 10,
        "spread_regime_dev": 5.0,
        "suppress_factor_one": 2,
        "suppress_factor_two": 4,
    }

    TAKER = {
        "combo_threshold": 0.5,
        "imb_threshold": 0.4,
        "consecutive_ticks": 1,
        "cooldown_ticks": 80,
        "clip": 4,
        "max_position": 100,
        "history_size": 4,
    }

    JOIN = {
        "offset_one": 5,
        "offset_two": 7,
        "clip": 6,
        "min_join_edge": 1,
    }

    def _book_signals(self, od: OrderDepth) -> Dict[str, float]:
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
            "spread": best_ask - best_bid,
            "bv1": bv1,
            "av1": av1,
            "microprice": microprice,
            "imb1": imb1,
            "mp_dev": mp_dev,
            "wall_dev": wall_dev,
            "combo_sig": combo_sig,
        }

    def _directional_bias(
        self,
        sig: Dict[str, float],
        rolling_mean: Optional[float],
        mid_diff_3: Optional[float],
    ) -> int:
        cfg = self.HYDROGEL
        score = 0
        thr = float(cfg["reversion_threshold"])
        thr_strong = float(cfg["reversion_threshold_strong"])

        if rolling_mean is not None:
            dev = rolling_mean - sig["mid"]
            if dev >= thr_strong:
                score += 2
            elif dev >= thr:
                score += 1
            elif dev <= -thr_strong:
                score -= 2
            elif dev <= -thr:
                score -= 1

            spread_narrow = int(cfg["spread_narrow"])
            spread_dev_thr = float(cfg["spread_regime_dev"])
            if sig["spread"] <= spread_narrow:
                stretch = sig["mid"] - rolling_mean
                if stretch >= spread_dev_thr:
                    score -= 1
                elif stretch <= -spread_dev_thr:
                    score += 1

        if mid_diff_3 is not None:
            shock_thr = float(cfg["tick_shock_threshold"])
            if mid_diff_3 >= shock_thr:
                score -= 1
            elif mid_diff_3 <= -shock_thr:
                score += 1

        return max(-2, min(2, score))

    def hydrogel_passive_orders(
        self,
        sig: Dict[str, float],
        position: int,
        rolling_mean: Optional[float],
        bias: int,
        passive_buy_taken: int,
        passive_sell_taken: int,
    ) -> List[Order]:
        cfg = self.HYDROGEL
        jcfg = self.JOIN
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
        step = float(cfg["reversion_step"])
        shift_clip = int(cfg["reversion_shift_clip"])
        rev_shift = (
            int(round(deviation / step)) if rolling_mean is not None else 0
        )
        rev_shift = max(-shift_clip, min(shift_clip, rev_shift))

        signal_shift = max(
            -shift_clip,
            min(shift_clip, mp_shift + rev_shift),
        )

        skew_int = int(round(position / float(cfg["skew_unit"])))
        position_dir = 1 if position > 0 else (-1 if position < 0 else 0)
        if bias != 0 and bias * position_dir > 0:
            skew_int = 0

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
        if bias >= 1:
            buy_limit = reversion_cap
            sell_limit = base_cap
        elif bias <= -1:
            buy_limit = base_cap
            sell_limit = reversion_cap
        else:
            buy_limit = base_cap
            sell_limit = base_cap

        primary_clip = int(cfg["primary_clip"])
        deeper_clip = int(cfg["deeper_clip"])
        join_clip = int(jcfg["clip"])
        join_offset_one = int(jcfg["offset_one"])
        join_offset_two = int(jcfg["offset_two"])
        min_join_edge = float(jcfg["min_join_edge"])

        buy_clip_primary = primary_clip
        sell_clip_primary = primary_clip
        buy_clip_deeper = deeper_clip
        sell_clip_deeper = deeper_clip

        s1 = int(cfg["suppress_factor_one"])
        s2 = int(cfg["suppress_factor_two"])
        if bias >= 2:
            sell_clip_primary = max(1, primary_clip // s2)
            sell_clip_deeper = max(1, deeper_clip // s2)
        elif bias >= 1:
            sell_clip_primary = max(1, primary_clip // s1)
            sell_clip_deeper = max(1, deeper_clip // s1)
        elif bias <= -2:
            buy_clip_primary = max(1, primary_clip // s2)
            buy_clip_deeper = max(1, deeper_clip // s2)
        elif bias <= -1:
            buy_clip_primary = max(1, primary_clip // s1)
            buy_clip_deeper = max(1, deeper_clip // s1)

        buy_capacity = buy_limit - position - passive_buy_taken
        sell_capacity = sell_limit + position - passive_sell_taken
        min_edge = float(cfg["min_edge"])

        orders: List[Order] = []

        if (
            buy_capacity > 0
            and deeper_buy < best_ask
            and (mid - deeper_buy) >= min_edge
        ):
            qty = min(buy_clip_deeper, buy_capacity)
            if qty > 0:
                orders.append(Order(self.PRODUCT, int(deeper_buy), qty))
                buy_capacity -= qty

        if (
            buy_capacity > 0
            and buy_price < best_ask
            and (mid - buy_price) >= min_edge
        ):
            qty = min(buy_clip_primary, buy_capacity)
            if qty > 0:
                orders.append(Order(self.PRODUCT, int(buy_price), qty))
                buy_capacity -= qty

        if (
            sell_capacity > 0
            and deeper_sell > best_bid
            and (deeper_sell - mid) >= min_edge
        ):
            qty = min(sell_clip_deeper, sell_capacity)
            if qty > 0:
                orders.append(Order(self.PRODUCT, int(deeper_sell), -qty))
                sell_capacity -= qty

        if (
            sell_capacity > 0
            and sell_price > best_bid
            and (sell_price - mid) >= min_edge
        ):
            qty = min(sell_clip_primary, sell_capacity)
            if qty > 0:
                orders.append(Order(self.PRODUCT, int(sell_price), -qty))
                sell_capacity -= qty

        # Strategy 1 probe: aggressive join layer when bias is strong.
        if bias >= 1 and buy_capacity > 0:
            offset = join_offset_two if bias >= 2 else join_offset_one
            join_buy = best_bid + offset
            join_buy = min(join_buy, best_ask - 1)
            if (mid - join_buy) >= min_join_edge:
                qty = min(join_clip, buy_capacity)
                if qty > 0:
                    orders.append(Order(self.PRODUCT, int(join_buy), qty))
                    buy_capacity -= qty

        if bias <= -1 and sell_capacity > 0:
            offset = join_offset_two if bias <= -2 else join_offset_one
            join_sell = best_ask - offset
            join_sell = max(join_sell, best_bid + 1)
            if (join_sell - mid) >= min_join_edge:
                qty = min(join_clip, sell_capacity)
                if qty > 0:
                    orders.append(Order(self.PRODUCT, int(join_sell), -qty))
                    sell_capacity -= qty

        return orders

    def hydrogel_taker_orders(
        self,
        sig: Dict[str, float],
        od: OrderDepth,
        position: int,
        trader_data: Dict[str, Any],
        timestamp: int,
        bias: int,
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

        if bias >= 1:
            short_signal = False
        if bias <= -1:
            long_signal = False

        clip = int(tcfg["clip"])
        max_pos = min(int(tcfg["max_position"]), int(cfg["position_limit"]))
        orders: List[Order] = []

        best_bid = sig["best_bid"]
        best_ask = sig["best_ask"]

        if long_signal and position < max_pos:
            available = -od.sell_orders.get(best_ask, 0)
            qty = min(clip, max_pos - position, available)
            if qty > 0:
                orders.append(Order(self.PRODUCT, int(best_ask), qty))
                trader_data["last_take_time"] = timestamp
        elif short_signal and position > -max_pos:
            available = od.buy_orders.get(best_bid, 0)
            qty = min(clip, max_pos + position, available)
            if qty > 0:
                orders.append(Order(self.PRODUCT, int(best_bid), -qty))
                trader_data["last_take_time"] = timestamp

        return orders

    def _update_mids(
        self, trader_data: Dict[str, Any], mid: float
    ) -> tuple:
        cfg = self.HYDROGEL
        window = int(cfg["rolling_window"])
        warmup = int(cfg["rolling_warmup"])
        shock_window = int(cfg["tick_shock_window"])

        mids = trader_data.get("hydrogel_mids", [])
        if not isinstance(mids, list):
            mids = []

        mid_diff_n: Optional[float] = None
        if len(mids) >= shock_window:
            mid_diff_n = mid - (mids[-shock_window] / 2.0)

        rolling_mean: Optional[float] = None
        if len(mids) >= warmup:
            rolling_mean = sum(mids) / (2.0 * len(mids))

        mids.append(int(round(mid * 2)))
        if len(mids) > window:
            mids = mids[-window:]
        trader_data["hydrogel_mids"] = mids

        return rolling_mean, mid_diff_n

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
            rolling_mean, mid_diff_n = self._update_mids(trader_data, sig["mid"])
            bias = self._directional_bias(sig, rolling_mean, mid_diff_n)

            position = state.position.get(self.PRODUCT, 0)

            taker_orders = self.hydrogel_taker_orders(
                sig=sig,
                od=od,
                position=position,
                trader_data=trader_data,
                timestamp=state.timestamp,
                bias=bias,
            )
            passive_buy_taken = sum(o.quantity for o in taker_orders if o.quantity > 0)
            passive_sell_taken = sum(-o.quantity for o in taker_orders if o.quantity < 0)

            passive_orders = self.hydrogel_passive_orders(
                sig=sig,
                position=position,
                rolling_mean=rolling_mean,
                bias=bias,
                passive_buy_taken=passive_buy_taken,
                passive_sell_taken=passive_sell_taken,
            )

            orders = taker_orders + passive_orders
            if orders:
                result[self.PRODUCT] = orders

        return result, conversions, json.dumps(trader_data, separators=(",", ":"))
