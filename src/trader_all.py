"""
Round 3 trader for ALL products: HYDROGEL_PACK, VELVETFRUIT_EXTRACT, and
the 6 active VEV vouchers (5000, 5100, 5200, 5300, 5400, 5500).

Strategies (see results/findings_*.md for the analysis behind each):
  - VELVETFRUIT_EXTRACT: layered passive market-making around wall_mid (EMA-
    smoothed). Inventory-aware quote sizing + take threshold + per-layer
    touch caps that prevent the v2 adverse-selection bug.
  - HYDROGEL_PACK: same MM template but with a wider half-spread to fit the
    ~16-tick observed spread.
  - VEV vouchers: IV scalping. Per strike each tick, compute the BS theo
    price using a polynomial smile fit. theo_diff = market - theo. EMA of
    theo_diff is the strike's running fair. Trade dev = theo_diff - EMA
    against an activation gate (EMA of |dev|).
  - Deep ITM (VEV_4000, VEV_4500) and floor-stuck (VEV_6000, VEV_6500)
    vouchers are ignored — see findings for why.

State persisted in traderData (jsonpickle):
  {
    "vfx_ema": float | None,       # EMA of wall_mid for VELVETFRUIT_EXTRACT
    "hyd_ema": float | None,       # EMA of wall_mid for HYDROGEL_PACK
    "vev": {
      "VEV_5000": {"mean_diff": float, "switch": float, "prev_dev": float},
      ...
    }
  }
"""

from typing import Dict, List, Tuple, Optional
import math
import jsonpickle

from datamodel import Order, OrderDepth, TradingState


# ---------- shared constants ----------
DAYS_PER_YEAR = 365
TICKS_PER_DAY = 1_000_000  # state.timestamp grows in steps of 100; a "day" = 1M

# Smile coefficients for IV vs m_t = log(K/S)/sqrt(T).
# Polynomial: IV = a*m_t^2 + b*m_t + c (np.poly1d order, highest first)
SMILE_A = 0.029118
SMILE_B = 0.002371
SMILE_C = 0.239486


# ---------- Black-Scholes (no scipy; uses math.erf) ----------
def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))


def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(0.0, S - K)
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return S * _ncdf(d1) - K * _ncdf(d2)


def bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0:
        return 1.0 if S > K else 0.0
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    return _ncdf(d1)


def bs_vega(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    return S * _npdf(d1) * sqrtT


def smile_iv(m_t: float) -> float:
    return SMILE_A * m_t * m_t + SMILE_B * m_t + SMILE_C


# ---------- helpers ----------
def best_bid_ask(depth: OrderDepth) -> Optional[Tuple[int, int]]:
    if not depth.buy_orders or not depth.sell_orders:
        return None
    return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())


def wall_mid(depth: OrderDepth) -> Optional[float]:
    """Midpoint of the highest-volume bid level and the highest-volume ask level."""
    if not depth.buy_orders or not depth.sell_orders:
        return None
    wb = max(depth.buy_orders.items(), key=lambda kv: abs(kv[1]))[0]
    wa = max(depth.sell_orders.items(), key=lambda kv: abs(kv[1]))[0]
    return (wb + wa) / 2.0


def update_ema(prev: Optional[float], value: float, alpha: float) -> float:
    if prev is None:
        return value
    return alpha * value + (1.0 - alpha) * prev


# ---------- Market-maker module (used for VELVETFRUIT_EXTRACT and HYDROGEL_PACK) ----------
class _MarketMaker:
    """
    Layered passive market-maker around an EMA-smoothed wall_mid fair value.
    All v3 fixes: per-layer touch caps, asymmetric inventory sizing,
    inventory-aware take threshold.
    """

    def __init__(
        self,
        product: str,
        position_limit: int,
        ema_alpha: float,
        half_spread: float,
        inventory_skew: float,
        gap_lean: float,
        take_base: float,
        take_inv_penalty: float,
        max_quote_size: int,
        quote_shrink_per_unit: float,
        layer_offsets: Tuple[float, ...] = (1.0, 2.0, 3.0),
        layer_weights: Tuple[float, ...] = (0.5, 0.3, 0.2),
        layer_touch_offsets: Tuple[int, ...] = (1, 0, -1),
    ):
        self.product = product
        self.position_limit = position_limit
        self.ema_alpha = ema_alpha
        self.half_spread = half_spread
        self.inventory_skew = inventory_skew
        self.gap_lean = gap_lean
        self.take_base = take_base
        self.take_inv_penalty = take_inv_penalty
        self.max_quote_size = max_quote_size
        self.quote_shrink_per_unit = quote_shrink_per_unit
        self.layer_offsets = layer_offsets
        self.layer_weights = layer_weights
        self.layer_touch_offsets = layer_touch_offsets

    def step(
        self,
        depth: OrderDepth,
        position: int,
        ema: Optional[float],
    ) -> Tuple[List[Order], float]:
        wm = wall_mid(depth)
        new_ema = update_ema(ema, wm, self.ema_alpha) if wm is not None else (ema if ema is not None else 0.0)

        ba = best_bid_ask(depth)
        if ba is None or wm is None:
            return [], new_ema
        best_bid, best_ask = ba

        raw_mid = (best_bid + best_ask) / 2.0
        fair = new_ema
        gap = raw_mid - fair

        reservation = fair - self.inventory_skew * position - self.gap_lean * gap

        buy_room = self.position_limit - position
        sell_room = self.position_limit + position

        orders: List[Order] = []

        # ----- 1) take obvious mispricings (inventory-aware threshold) -----
        take_buy_thr = self.take_base + self.take_inv_penalty * max(0, position)
        take_sell_thr = self.take_base + self.take_inv_penalty * max(0, -position)

        if best_ask < fair - take_buy_thr and buy_room > 0:
            ask_avail = -depth.sell_orders[best_ask]
            qty = min(ask_avail, buy_room)
            if qty > 0:
                orders.append(Order(self.product, best_ask, qty))
                buy_room -= qty
                position += qty

        if best_bid > fair + take_sell_thr and sell_room > 0:
            bid_avail = depth.buy_orders[best_bid]
            qty = min(bid_avail, sell_room)
            if qty > 0:
                orders.append(Order(self.product, best_bid, -qty))
                sell_room -= qty
                position -= qty

        # ----- 2) layered passive quotes with asymmetric sizing + touch caps -----
        bid_unfav = position > 0
        ask_unfav = position < 0

        bid_size_cap = self.max_quote_size
        ask_size_cap = self.max_quote_size
        if bid_unfav:
            bid_size_cap = max(0, int(self.max_quote_size - self.quote_shrink_per_unit * position))
        if ask_unfav:
            ask_size_cap = max(0, int(self.max_quote_size - self.quote_shrink_per_unit * (-position)))

        bid_room = min(bid_size_cap, max(0, buy_room))
        ask_room = min(ask_size_cap, max(0, sell_room))

        # bid layers
        remaining = bid_room
        for offset, weight, touch_off in zip(self.layer_offsets, self.layer_weights, self.layer_touch_offsets):
            if remaining <= 0:
                break
            qty = min(int(round(self.max_quote_size * weight)), remaining)
            if qty <= 0:
                continue
            price = int(round(reservation - offset * self.half_spread))
            price = min(price, best_bid + touch_off, best_ask - 1)
            orders.append(Order(self.product, price, qty))
            remaining -= qty

        # ask layers
        remaining = ask_room
        for offset, weight, touch_off in zip(self.layer_offsets, self.layer_weights, self.layer_touch_offsets):
            if remaining <= 0:
                break
            qty = min(int(round(self.max_quote_size * weight)), remaining)
            if qty <= 0:
                continue
            price = int(round(reservation + offset * self.half_spread))
            price = max(price, best_ask - touch_off, best_bid + 1)
            orders.append(Order(self.product, price, -qty))
            remaining -= qty

        return orders, new_ema


# ---------- VEV scalper (one method, run per strike) ----------
class _VEVScalper:
    """
    IV scalping for one VEV strike.
    Maintains EMA(theo_diff) (the strike's running fair) and EMA(|dev|) (gate).
    """

    # Faster EMAs so the gate ramps up within the simulator window
    EMA_FAST_ALPHA = 2.0 / (20 + 1)    # window 20 -> alpha 0.0952
    EMA_SWITCH_ALPHA = 2.0 / (50 + 1)  # window 50 -> alpha 0.0392 (was 100)

    # Dynamic thresholds — relative to the strike's own running |dev| (switch_mean).
    # The signal must clear BOTH a noise floor AND the half-spread cost of
    # crossing to fill. Hedgehogs' implicit formula was:
    #   dev + (best_bid - wall_mid) >= THR_OPEN + low_vega_adj
    # which rearranges to: dev >= THR_OPEN + half_spread + low_vega_adj
    # We bake half_spread in explicitly below.
    OPEN_K = 2.5            # open when |dev| > OPEN_K * switch_mean (+ spread)
    CLOSE_K = 0.5           # close when |dev| < CLOSE_K * switch_mean
    THR_OPEN_FLOOR = 0.30   # absolute minimum signal magnitude on top of spread
    THR_ACTIVATE = 0.05     # absolute minimum switch_mean for the gate
    LOW_VEGA_THR_ADJ = 0.20 # extra threshold for low-vega strikes
    LOW_VEGA_LIMIT = 100.0
    POSITION_LIMIT = 300
    MAX_FILL_PER_TICK = 30  # cap on lift/hit size per tick (don't sweep books)

    # Per-strike seed values from historical analysis. These let the gate be
    # alive from tick 1 instead of warming up for 50–100 ticks.
    SEED_MEAN_DIFF = {
        5000: -0.05, 5100: -0.07, 5200: 0.72,
        5300: 1.32, 5400: -2.20, 5500: 0.53,
    }
    SEED_SWITCH = {
        5000: 0.18, 5100: 0.20, 5200: 0.16,
        5300: 0.16, 5400: 0.13, 5500: 0.15,
    }

    def __init__(self, product: str, strike: int):
        self.product = product
        self.strike = strike

    def step(
        self,
        depth: OrderDepth,
        position: int,
        S: float,
        T: float,
        prev_state: Dict,
    ) -> Tuple[List[Order], Dict]:
        """
        Returns (orders, updated_state). prev_state has keys mean_diff, switch.
        """
        new_state = dict(prev_state)  # copy

        wm = wall_mid(depth)
        ba = best_bid_ask(depth)
        if wm is None or ba is None or T <= 0 or S <= 0:
            return [], new_state
        best_bid, best_ask = ba

        # Smile-based fair IV and theoretical price
        m_t = math.log(self.strike / S) / math.sqrt(T)
        sigma = max(1e-4, smile_iv(m_t))
        theo = bs_call(S, self.strike, T, sigma)
        vega = bs_vega(S, self.strike, T, sigma)

        theo_diff = wm - theo

        # seed EMAs on first tick from historical per-strike averages (so the
        # activation gate is alive immediately instead of warming up 50+ ticks)
        prev_mean = prev_state.get("mean_diff", self.SEED_MEAN_DIFF.get(self.strike, 0.0))
        prev_switch = prev_state.get("switch", self.SEED_SWITCH.get(self.strike, 0.15))

        new_mean = update_ema(prev_mean, theo_diff, self.EMA_FAST_ALPHA)
        new_state["mean_diff"] = new_mean

        dev = theo_diff - new_mean

        new_switch = update_ema(prev_switch, abs(dev), self.EMA_SWITCH_ALPHA)
        new_state["switch"] = new_switch

        orders: List[Order] = []

        low_vega_adj = self.LOW_VEGA_THR_ADJ if vega <= self.LOW_VEGA_LIMIT else 0.0
        half_spread = (best_ask - best_bid) / 2.0
        # signal must clear: spread cost + signal-vs-noise + low-vega adj + floor
        open_thr = (
            half_spread
            + max(self.THR_OPEN_FLOOR, self.OPEN_K * new_switch)
            + low_vega_adj
        )
        close_thr = self.CLOSE_K * new_switch

        buy_room = self.POSITION_LIMIT - position
        sell_room = self.POSITION_LIMIT + position

        # gate: if the strike's typical |dev| is too small, signal is noise
        if new_switch < self.THR_ACTIVATE:
            if position > 0:
                avail = depth.buy_orders.get(best_bid, 0)
                qty = min(avail, position)
                if qty > 0:
                    orders.append(Order(self.product, best_bid, -qty))
            elif position < 0:
                avail = -depth.sell_orders.get(best_ask, 0)
                qty = min(avail, -position)
                if qty > 0:
                    orders.append(Order(self.product, best_ask, qty))
            return orders, new_state

        # signal alive — open / close per dynamic thresholds
        if dev > open_thr and sell_room > 0:
            avail = depth.buy_orders.get(best_bid, 0)
            qty = min(avail, sell_room, self.MAX_FILL_PER_TICK)
            if qty > 0:
                orders.append(Order(self.product, best_bid, -qty))
        elif dev < -open_thr and buy_room > 0:
            avail = -depth.sell_orders.get(best_ask, 0)
            qty = min(avail, buy_room, self.MAX_FILL_PER_TICK)
            if qty > 0:
                orders.append(Order(self.product, best_ask, qty))
        elif abs(dev) < close_thr:
            # crossed back near mean — flatten existing
            if position > 0:
                avail = depth.buy_orders.get(best_bid, 0)
                qty = min(avail, position)
                if qty > 0:
                    orders.append(Order(self.product, best_bid, -qty))
            elif position < 0:
                avail = -depth.sell_orders.get(best_ask, 0)
                qty = min(avail, -position)
                if qty > 0:
                    orders.append(Order(self.product, best_ask, qty))

        return orders, new_state


# ---------- Top-level Trader ----------
VFX_PRODUCT = "VELVETFRUIT_EXTRACT"
HYD_PRODUCT = "HYDROGEL_PACK"
VEV_STRIKES = {
    "VEV_5000": 5000,
    "VEV_5100": 5100,
    "VEV_5200": 5200,
    "VEV_5300": 5300,
    "VEV_5400": 5400,
    "VEV_5500": 5500,
}

# Kill switch — VEV scalping is currently disabled while the options
# strategy is being redesigned. Set to True to re-enable.
VEV_TRADING_ENABLED = False


class Trader:
    def __init__(self):
        # VELVETFRUIT_EXTRACT — narrow 5-tick spread, our well-tested params
        self.vfx_mm = _MarketMaker(
            product=VFX_PRODUCT,
            position_limit=200,
            ema_alpha=0.30,
            half_spread=1.5,
            inventory_skew=0.05,
            gap_lean=0.6,
            take_base=1.5,
            take_inv_penalty=0.05,
            max_quote_size=25,
            quote_shrink_per_unit=0.5,
        )
        # HYDROGEL_PACK — wide ~16-tick spread, larger quote distances
        self.hyd_mm = _MarketMaker(
            product=HYD_PRODUCT,
            position_limit=200,
            ema_alpha=0.20,
            half_spread=4.0,         # quote layers at ~4/8/12 ticks below resv
            inventory_skew=0.15,     # bigger pull because each tick is worth more
            gap_lean=0.5,
            take_base=5.0,           # wider take threshold (16-tick spread)
            take_inv_penalty=0.10,
            max_quote_size=20,
            quote_shrink_per_unit=0.4,
            layer_offsets=(1.0, 2.0, 3.0),
            layer_touch_offsets=(2, 0, -2),  # innermost ~2 ticks inside touch
        )
        # VEV scalpers
        self.vev_scalpers = {
            sym: _VEVScalper(sym, K) for sym, K in VEV_STRIKES.items()
        }

    @staticmethod
    def _decode_state(s: str) -> Dict:
        if not s:
            return {"vfx_ema": None, "hyd_ema": None, "vev": {}}
        try:
            blob = jsonpickle.decode(s)
            if not isinstance(blob, dict):
                return {"vfx_ema": None, "hyd_ema": None, "vev": {}}
            blob.setdefault("vev", {})
            return blob
        except Exception:
            return {"vfx_ema": None, "hyd_ema": None, "vev": {}}

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        td = self._decode_state(state.traderData)
        all_orders: Dict[str, List[Order]] = {}

        # underlying S for option pricing — wall_mid of velvetfruit (or fall back to mid)
        vfx_depth = state.order_depths.get(VFX_PRODUCT)
        S = wall_mid(vfx_depth) if vfx_depth is not None else None

        # ---- VELVETFRUIT_EXTRACT market-making ----
        if vfx_depth is not None:
            pos = state.position.get(VFX_PRODUCT, 0)
            orders, new_ema = self.vfx_mm.step(vfx_depth, pos, td.get("vfx_ema"))
            td["vfx_ema"] = new_ema
            if orders:
                all_orders[VFX_PRODUCT] = orders

        # ---- HYDROGEL_PACK market-making ----
        hyd_depth = state.order_depths.get(HYD_PRODUCT)
        if hyd_depth is not None:
            pos = state.position.get(HYD_PRODUCT, 0)
            orders, new_ema = self.hyd_mm.step(hyd_depth, pos, td.get("hyd_ema"))
            td["hyd_ema"] = new_ema
            if orders:
                all_orders[HYD_PRODUCT] = orders

        # ---- VEV vouchers ----
        if VEV_TRADING_ENABLED and S is not None and S > 0:
            # TTE: vouchers expire 7d from round-1 start. Round 3 starts at TTE=5d.
            # state.timestamp resets to 0 at the start of each round, ranges 0..1e6
            # per simulated day. So during round 3, T_days = 5 - timestamp/1e6.
            # (For backtests on historical data this gives the right answer because
            # the backtester also uses 0..1e6 timestamps; only the absolute TTE
            # offset differs, which is fine as long as the smile fit was made on
            # the same scale.)
            T = max(1e-6, (5.0 - state.timestamp / TICKS_PER_DAY) / DAYS_PER_YEAR)

            vev_state = td.get("vev", {})
            for sym, scalper in self.vev_scalpers.items():
                depth = state.order_depths.get(sym)
                if depth is None:
                    continue
                pos = state.position.get(sym, 0)
                prev = vev_state.get(sym, {})
                orders, new_state = scalper.step(depth, pos, S, T, prev)
                vev_state[sym] = new_state
                if orders:
                    all_orders[sym] = orders
            td["vev"] = vev_state

        try:
            trader_data = jsonpickle.encode(td)
        except Exception:
            trader_data = ""

        return all_orders, 0, trader_data

    # Round 2 leftover; harmless if unused.
    def bid(self) -> int:
        return 0
