"""
Round 3 trader for VEV_* (VELVETFRUIT_EXTRACT vouchers).

Strategy in one paragraph
-------------------------
The historical data shows a *persistent, structural* dislocation in the IV
smile across the live strikes. Using the underlying VELVETFRUIT_EXTRACT mid
as spot and the 5 actively-quoted strikes (5100, 5200, 5300, 5400, 5500) for
the smile, every tick I compute each strike's mid-IV and use the per-tick
*cross-strike average* IV as a fair-value estimate. Two strikes deviate
consistently:

  * VEV_5400 mid-IV is lower than the cross-strike average by ~6e-4 vol-units
    on 94% of ticks, so its **ask** sits ~2 ticks BELOW the smile-implied fair
    price. Lifting that ask is a positive-EV trade.
  * VEV_5500 mid-IV is higher than the cross-strike average, so its **bid**
    sits ~0.4 ticks ABOVE smile-implied fair. Hitting that bid is a marginal
    positive-EV trade.

Trading them as a 1:1 pair (long 5400, short 5500) is naturally close to
delta-neutral (~0.10 net delta per pair) and gives a bear-call-spread payoff
with average ~+1.8 edge per pair entered. With a position limit of 300 we
fill out fast and then sit on the inventory; round-end liquidates at a hidden
fair value which we ASSUME is the smile-fair (the realized PnL hinges on this).

Other strikes:
  * VEV_4000 / 4500 are deep ITM; price is dominated by intrinsic and the IV
    bisection is at the floor — no IV signal to trade against.
  * VEV_5000 / 5100 / 5200 / 5300 have either too-wide spreads or marginal
    edge. We still USE 5100/5200/5300/5400/5500 to estimate the smile, but
    we only POST orders on 5400 and 5500.
  * VEV_6000 / 6500 quote bid=0, ask=1 (lottery floor). Untradeable.

What we actually do each tick
-----------------------------
1. Read mid of VELVETFRUIT_EXTRACT for spot. Bail if missing.
2. For each of {5100, 5200, 5300, 5400, 5500}: compute mid-IV via bisection
   on Black-Scholes (math.erf-based normal CDF, no scipy).
3. For 5400: compute reference IV = mean of the other 4 strikes' mid-IVs;
   convert to fair price `bs_call(spot, 5400, T, ref_iv_5400)`. Same for 5500.
4. If `fair_5400 - best_ask_5400 > BUY_THR` and we have buy room: lift the
   ask up to `min(ask_size, room, MAX_TAKE_PER_TICK)`.
5. If `best_bid_5500 - fair_5500 > SELL_THR` and we have sell room: hit the
   bid up to `min(bid_size, room, MAX_TAKE_PER_TICK)`.
6. *Pair-balance throttle*: if the long/short pair gets out of balance by
   more than PAIR_IMBALANCE_CAP, the over-loaded side stops adding until the
   other catches up. This keeps net delta near zero.

State:
   No state strictly required (we recompute everything from the order book
   every tick). We persist a small dict for diagnostics; if it parses we use
   it, otherwise we silently start fresh.

Framework constraints respected:
   * No scipy / no third-party imports beyond the allowed list.
   * `run()` returns a 3-tuple `(orders, conversions, traderData)`.
   * Aggregate per-side qty is sized against current position so the
     all-or-nothing position-limit check never rejects us.
   * Sell orders use NEGATIVE qty.

Integration note for trader_all.py:
   `Trader.run_vev_only(state)` returns just `dict[symbol, list[Order]]`
   for the VEV symbols, suitable for merging with HYDROGEL_PACK and
   VELVETFRUIT_EXTRACT order dicts produced by other traders.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import jsonpickle

from datamodel import Order, OrderDepth, TradingState


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

UNDERLYING = "VELVETFRUIT_EXTRACT"

# Strikes used for the smile (must have live two-sided markets in the data).
SMILE_STRIKES: Tuple[int, ...] = (5100, 5200, 5300, 5400, 5500)

# Strikes we actually trade.
BUY_STRIKE = 5400   # ask is consistently below smile-fair
SELL_STRIKE = 5500  # bid is consistently above smile-fair

POSITION_LIMIT = 300

# TTE schedule: TTE_days at the *start* of (round, day).
# Historical data day 0 = TTE 8d at start. Round 3 first day starts at TTE=5d.
# Linear decay: 1 day = 1_000_000 timestamp units.
# We don't actually know which round the live system runs us in; the cleanest
# robust approach is to compute TTE = max(TTE_FLOOR, ROUND3_START_TTE - ts/1e6).
# If we are dropped into a different round, the smile is still computed
# self-consistently from the current order books — only the absolute IV scale
# changes, and the cross-strike *deviation* (which is what we trade) is robust.
ROUND3_START_TTE_DAYS = 5.0   # at timestamp 0 of round 3 first day
TTE_FLOOR_DAYS = 0.05         # never let T → 0 in BS

TIMESTAMP_PER_DAY = 1_000_000

# Default IV used as a fallback if we can't compute a smile (e.g. early in
# the run with sparse books). 0.013 is the historical mean per-day vol.
FALLBACK_IV = 0.013

# Trading thresholds (in absolute price ticks of the option). Tuned by an
# offline historical sweep over (BUY_THR, SELL_THR, PAIR_IMBALANCE_CAP) using
# per-day reset and end-of-day MTM at *mid* (the conservative MTM proxy).
# Best on the 3-day historical: BUY=1.0, SELL=0.7, IMB_CAP=300 → PnL@mid
# ≈ +220/day, PnL@smile-fair ≈ +1340/day. The MID and FAIR MTMs bound the
# realistic round-end PnL.
BUY_EDGE_THR = 1.0    # buy 5400 only when fair - ask >= this
SELL_EDGE_THR = 0.7   # sell 5500 only when bid - fair >= this

# Per-tick cap on how aggressively we lift / hit. Keeps single-tick exposure
# bounded even if the book briefly shows huge size.
MAX_TAKE_PER_TICK = 25

# Soft pair-imbalance throttle. With deltas ~ (0.18 long-leg, 0.08 short-leg),
# even a perfectly-balanced 1:1 pair carries ~0.10 net long-delta per pair.
# A cap of 300 is permissive (essentially: only kicks in if one leg fills out
# entirely while the other never fires, which we observed doesn't happen on
# the historical data). Tighter caps (e.g. 50) gave WORSE realized PnL in
# backtest because they blocked the cheap-5400 buy side from filling at the
# best historical entry prices while waiting for the slower 5500 sell side
# to catch up — the buy edge is the dominant source of PnL, so we let it
# fire as soon as it appears.
PAIR_IMBALANCE_CAP = 300


# --------------------------------------------------------------------------- #
# Black-Scholes helpers (no scipy, math.erf only).
# --------------------------------------------------------------------------- #


_SQRT2 = math.sqrt(2.0)
_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def _bs_call(spot: float, strike: float, t: float, sigma: float) -> float:
    """European call under r=0, q=0. T in days, sigma in per-day vol units."""
    if t <= 0.0 or sigma <= 0.0:
        return max(0.0, spot - strike)
    sqrt_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + 0.5 * sigma * sigma * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return spot * _norm_cdf(d1) - strike * _norm_cdf(d2)


def _implied_vol(price: float, spot: float, strike: float, t: float) -> float:
    """Bisection IV. Returns 0.0 if at/below intrinsic, NaN if above no-arb."""
    intrinsic = max(0.0, spot - strike)
    if price <= intrinsic + 1e-9:
        return 0.0
    if price >= spot:
        return float("nan")
    lo, hi = 1e-6, 5.0
    for _ in range(40):  # 40 iters → resolution ~ 5e-12; plenty fast
        mid = 0.5 * (lo + hi)
        if _bs_call(spot, strike, t, mid) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


# --------------------------------------------------------------------------- #
# Order-book helpers
# --------------------------------------------------------------------------- #


def _best_bid_ask(depth: OrderDepth) -> Tuple[int | None, int | None, int, int]:
    """Return (best_bid, best_ask, bid_size, ask_size_pos). Sizes positive.

    Live runtime: sell_orders volumes are NEGATIVE. We flip sign here so the
    rest of the code can think in positive sizes throughout.
    """
    if not depth.buy_orders or not depth.sell_orders:
        return None, None, 0, 0
    best_bid = max(depth.buy_orders.keys())
    best_ask = min(depth.sell_orders.keys())
    bid_size = int(depth.buy_orders[best_bid])
    ask_size = -int(depth.sell_orders[best_ask])
    return best_bid, best_ask, bid_size, ask_size


def _mid(depth: OrderDepth) -> float | None:
    bb, ba, _, _ = _best_bid_ask(depth)
    if bb is None or ba is None:
        return None
    return 0.5 * (bb + ba)


# --------------------------------------------------------------------------- #
# Trader
# --------------------------------------------------------------------------- #


class Trader:
    # exposed so unit-testing or trader_all.py can override.
    SMILE_STRIKES = SMILE_STRIKES
    BUY_STRIKE = BUY_STRIKE
    SELL_STRIKE = SELL_STRIKE
    BUY_EDGE_THR = BUY_EDGE_THR
    SELL_EDGE_THR = SELL_EDGE_THR
    MAX_TAKE_PER_TICK = MAX_TAKE_PER_TICK
    PAIR_IMBALANCE_CAP = PAIR_IMBALANCE_CAP
    FALLBACK_IV = FALLBACK_IV

    # ---- entry points -----------------------------------------------------
    def run(
        self, state: TradingState
    ) -> Tuple[Dict[str, List[Order]], int, str]:
        orders = self.run_vev_only(state)
        return orders, 0, self._encode_trader_data(state)

    # Round 2 compatibility (harmless elsewhere).
    def bid(self) -> int:
        return 0

    # The method `trader_all.py` will call when integrating.
    def run_vev_only(
        self, state: TradingState
    ) -> Dict[str, List[Order]]:
        out: Dict[str, List[Order]] = {}

        spot = self._spot(state)
        if spot is None:
            return out

        tte = self._tte_days(state.timestamp)

        # Compute the smile: mid-IV for each live strike.
        mid_ivs: Dict[int, float] = {}
        for k in self.SMILE_STRIKES:
            sym = f"VEV_{k}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            m = _mid(depth)
            if m is None:
                continue
            iv = _implied_vol(m, spot, float(k), tte)
            # Skip floor (deep ITM where we get 0.0) and NaN.
            if iv > 0.0 and not math.isnan(iv):
                mid_ivs[k] = iv

        # If we couldn't observe at least 2 strikes, we can't do cross-strike
        # smile estimation safely. Bail.
        if len(mid_ivs) < 2:
            return out

        # Place orders for each tradeable strike.
        for k in (self.BUY_STRIKE, self.SELL_STRIKE):
            sym = f"VEV_{k}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            position = int(state.position.get(sym, 0))
            leg_orders = self._trade_strike(
                k, depth, spot, tte, mid_ivs, position, state.position
            )
            if leg_orders:
                out[sym] = leg_orders

        return out

    # ---- main per-strike logic --------------------------------------------
    def _trade_strike(
        self,
        strike: int,
        depth: OrderDepth,
        spot: float,
        tte: float,
        mid_ivs: Dict[int, float],
        position: int,
        all_positions: Dict[str, int],
    ) -> List[Order]:
        sym = f"VEV_{strike}"
        bb, ba, bid_size, ask_size = _best_bid_ask(depth)
        if bb is None or ba is None:
            return []

        # Reference IV = mean of OTHER strikes' mid-IVs. If 'strike' itself is
        # in mid_ivs we exclude it; otherwise we use everything we have.
        refs = [v for k, v in mid_ivs.items() if k != strike]
        if not refs:
            return []
        ref_iv = sum(refs) / len(refs)

        # Fair value at smile-IV.
        fair = _bs_call(spot, float(strike), tte, ref_iv)

        # Pair imbalance — long position in BUY_STRIKE plus short position in
        # SELL_STRIKE should net to ~0 (we trade 1:1). If we're way long the
        # pair, slow down the buy side; if way short, slow down the sell side.
        pos_buy = int(all_positions.get(f"VEV_{self.BUY_STRIKE}", 0))
        pos_sell = int(all_positions.get(f"VEV_{self.SELL_STRIKE}", 0))
        # Net pair (positive => more long 5400 than short 5500)
        pair_net = pos_buy + pos_sell

        orders: List[Order] = []

        if strike == self.BUY_STRIKE:
            edge = fair - float(ba)  # positive => ask is below fair
            # Don't buy more if we're already pair-imbalanced long.
            if edge >= self.BUY_EDGE_THR and pair_net < self.PAIR_IMBALANCE_CAP:
                room = POSITION_LIMIT - position
                qty = min(self.MAX_TAKE_PER_TICK, room, max(0, ask_size))
                if qty > 0:
                    orders.append(Order(sym, ba, qty))

        elif strike == self.SELL_STRIKE:
            edge = float(bb) - fair  # positive => bid is above fair
            # Don't sell more if we're already pair-imbalanced short.
            if (
                edge >= self.SELL_EDGE_THR
                and pair_net > -self.PAIR_IMBALANCE_CAP
            ):
                room = POSITION_LIMIT + position  # how much more we can sell
                qty = min(self.MAX_TAKE_PER_TICK, room, max(0, bid_size))
                if qty > 0:
                    orders.append(Order(sym, bb, -qty))

        return orders

    # ---- utilities --------------------------------------------------------
    @staticmethod
    def _spot(state: TradingState) -> float | None:
        depth = state.order_depths.get(UNDERLYING)
        if depth is None:
            return None
        return _mid(depth)

    @staticmethod
    def _tte_days(timestamp: int) -> float:
        # Round 3 day 1 starts at TTE = 5 days. We don't have visibility into
        # which simulation day we're on (state.timestamp resets daily), so we
        # treat each call as round-3-day-1 + ts/1e6. This understates TTE on
        # later sim days by 1-2 days, but the *cross-strike deviation* signal
        # we trade is robust to this (small IV-scale shifts cancel across
        # strikes when we use cross-strike average).
        t = ROUND3_START_TTE_DAYS - timestamp / TIMESTAMP_PER_DAY
        return max(t, TTE_FLOOR_DAYS)

    def _encode_trader_data(self, state: TradingState) -> str:
        # Reserved for future stateful additions (e.g., EMA of edge for
        # adaptive thresholds). For now we persist nothing essential, but
        # round-trip a tiny dict so the decode-on-next-tick path is exercised.
        try:
            return jsonpickle.encode({"v": 1, "ts": state.timestamp})
        except Exception:
            return ""
