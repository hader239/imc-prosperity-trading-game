# Round 4 HYDROGEL_PACK Strategy Catalog

## Question

Which market-data-only strategies have we tried on `HYDROGEL_PACK`, what
exactly does each one do, and what did the official Prosperity log say
about it?

## Context

- Round-4 product `HYDROGEL_PACK`, position limit `200`.
- Public spread is almost always `16` ticks (`27,754` of `30,000`
  historical rows). Narrow-spread regimes (`7-9`) are `~3%` of rows.
- Bot taker flow per 1k-tick test is `~134` units across `~32` events,
  almost entirely from one taker. This caps the absolute pure-passive
  market-making PnL at `~134 * 16 = 2,144` per 1k-tick test day.
- All strategies below are market-data only; no counterparty IDs are
  read from `state.market_trades`.
- Official 1k-tick test logs referenced: `524940`, `525326`, `525368`.

## Strategy Index

| # | Name | File | Status |
|---|---|---|---|
| 0 | Mark 14 / Mark 38 liquidity replacement | `src/trader_523197_mark14_liquidity.py` | superseded |
| 6 | Rolling-mean inventory carry (specialist v1) | `src/hydrogel_specialist.py` | tested `524940` |
| - | Passive v2 (tests 1+2+3 from chat plan) | `src/hydrogel_passive_v2.py` | tested `525326` |
| - | Active v1 (tests 1+2+3+4) | `src/hydrogel_active_v1.py` | tested `525368` |
| - | Active v2 (verified bias + skew decoupling) | `src/hydrogel_active_v2.py` | not yet tested |
| - | Active v3 (v2 + aggressive-join probe) | `src/hydrogel_active_v3.py` | not yet tested |

Per-strategy detail follows.

## Strategy 0 — Mark 14 / Mark 38 liquidity replacement

**File:** `src/trader_523197_mark14_liquidity.py` (HYDROGEL section).

**Idea.** Replace the historical `Mark 14` resting liquidity at the top
of the public spread by quoting one tick inside, so the bot taker
(`Mark 38`) hits us instead of `Mark 14`.

**Mechanics.**

1. Quote `best_bid + 1` and `best_ask - 1` only.
2. Single clip per side.
3. Inventory cap (`test_limit = 100`) and a fixed `min_edge = 5`.
4. Inventory skew via `position * inventory_skew = 0.08`.

**Tested.** Earlier probe runs in this lineage (`522985`, `523131`,
`523323`) — small, scaled, and 2-tick variants — produced HYDROGEL PnL
of `+212`, `+642`, `+841` respectively in 1k-tick tests.

**Result.** Validated that replacing the LP works mechanically (bots
take from us instead). Single edge layer, no directional or regime
information.

## Strategy 6 — Rolling-mean inventory carry (specialist v1)

**File:** `src/hydrogel_specialist.py`.

**Idea.** Add directional inventory carry: when mid is stretched far
from a rolling mean, allow accumulating a larger position on the
reversion side.

**Mechanics.**

1. Maintain a rolling history of `mid` in `traderData` over the last
   `1500` ticks (warmup `300`).
2. Compute `deviation = rolling_mean - mid`.
3. If `deviation >= 8` favor buy; if `deviation <= -8` favor sell.
4. Quote primary `best_bid + 1` / `best_ask - 1`, deeper `best_bid + 3`
   / `best_ask - 3`, plus a tiny microprice + wall-mid signal shift
   clipped to `±3` ticks.
5. `base_inventory_cap = 50`; on a favored side it expands to
   `reversion_inventory_cap = 140`.
6. Inventory skew of `position / 25` is applied to both quotes.

**Tested in `524940`.**

- HYDROGEL PnL: `+1097.75`.
- Own trades: `21` events, `89` units, end position `+5`.
- Per-unit edge: `~12.3` ticks.

**Findings.**

- Rolling-mean reversion conceptually correct, but the threshold of `8`
  ticks rarely fired on this day's slow drift.
- Inventory skew silently fought the rolling-mean reversion (see
  Strategy v2 / Active v2 for the fix).
- We captured `~67%` of HYDROGEL bot taker flow.

## Strategy v2 — Passive v2 (tests 1 + 2 + 3 from chat plan)

**File:** `src/hydrogel_passive_v2.py`.

**Three additions over Strategy 6.**

1. **Looser rolling-mean knobs.** `reversion_threshold` `8 -> 3`,
   `reversion_step` `12 -> 4`, `base_inventory_cap` `50 -> 80`,
   `reversion_inventory_cap` `140 -> 160`. Goal: actually trigger the
   directional carry on slow drift days.
2. **Top-of-book layer (`k=0`).** A third resting clip at `best_bid` /
   `best_ask`, sharing queue with the original LP. Goal: catch the
   fills the v1 specialist can never get when our `k=1` and `k=3`
   inventory is exhausted.
3. **Microprice / imbalance skew on the quote center.** With
   `microprice = (best_bid * av1 + best_ask * bv1) / (bv1 + av1)`,
   shift both quotes by `±1` tick when `|microprice - mid| >= 0.25`.
   Strongest short-horizon public signal in the data
   (`combo_sig` `+0.345` at 100-tick horizon).

**Tested in `525326`.**

- HYDROGEL PnL: `+1205.75`.
- Own trades: `18` events, `77` units, end position `-27`.
- Per-unit edge: `~15.6` ticks (better than Strategy 6).

**Findings.**

- Microprice skew helped: fewer fills, better-priced.
- Top-of-book `k=0` layer added zero fills. Bot taker clips are
  `4-6` units, fully absorbed by our existing inside-spread inventory
  (`k=3` clip `3` + `k=1` clip `8` = `11` units). Bots never reach
  `k=0`. Removed in `active_v2`.

## Strategy Active v1 (tests 1 + 2 + 3 + 4)

**File:** `src/hydrogel_active_v1.py`.

**Adds to Passive v2.**

4. **Imbalance-triggered taker.** Maintain short history of
   `combo_sig = 0.5 * (microprice - mid) + 0.5 * (wall_mid - mid)` and
   `imb1 = (bv1 - av1) / (bv1 + av1)`. When `|combo_sig| >= 1.0` OR
   `|imb1| >= 0.5` for two consecutive ticks AND cooldown of `100`
   ticks elapsed, take liquidity for `clip = 3` units at `best_ask`
   (long signal) or `best_bid` (short signal). Directional position
   capped at `±80`.

**Tested in `525368`.**

- HYDROGEL PnL: `+1329.50`.
- Own trades: `19` events, `80` units, end position `-30`.
- Active taker fired exactly once at `ts=60900`: sold `3 @ 10056` to
  `Mark 22` near the day's mid peak. Mid then dropped from `10060`
  to `10017`, so the trade contributed `~+42` realized edge plus
  `~+80` of end-of-day mark-to-market.

**Findings.**

- Active taker works mechanically.
- High threshold (`combo >= 1.0`, `consecutive 2`) is restrictive — it
  only fired once in 1k ticks. Lowered in `active_v2`.
- Crossing-style taking is roughly break-even at best given combo_sig
  slope vs spread cost; the value is in occasionally catching peaks,
  not in scalping each take.

## Strategy Active v2 (verified bias + skew decoupling)

**File:** `src/hydrogel_active_v2.py`.

**Replaces ad-hoc reversion / shift logic with a unified bias score.**

Bias score is an integer in `[-2, +2]` summing three verified directional
signals:

1. **Rolling-mean reversion (Strategy 6).** `+1` if mid below mean by
   `>=5`, `+2` if `>=10`. Symmetric.
2. **Spread-regime reversion (Strategy 4).** When `spread <= 10` and
   `|mid - rolling_mean| >= 5`, push bias one notch toward reversion.
   Verified historically: narrow spread + stretched up gives
   `r100 = -0.48` (n=358), narrow spread + stretched down gives
   `r100 = +0.97` (n=410).
3. **Tick-shock reversion (Strategy 9).** When `mid_diff_3 >= 5` push
   bias `-1`; when `<= -5` push bias `+1`. Verified historically:
   `r100 ≈ ±0.27` after 5-tick shock (n≈2.7k each side).

**Behavior changes driven by bias.**

- **Single-sided quoting (Strategy 2).** When `|bias| >= 1` the
  unfavored side's clip shrinks `2x`; at `|bias| >= 2` it shrinks
  `4x`.
- **Inventory cap expansion.** Favored side cap goes to
  `reversion_inventory_cap = 160`; unfavored stays at `base_cap = 80`.
- **Skew decoupling fix.** When `bias` matches the position direction,
  the inventory skew is set to `0`. Without this, the inventory skew
  silently pulls quotes back to neutral and prevents the directional
  inventory carry that the rolling-mean signal asks for. This is the
  v1/v2 bug that left us at `-30` when the signal wanted `-160`.
- **Lower-threshold imbalance taker.** `combo_threshold` `1.0 -> 0.5`,
  `consecutive_ticks` `2 -> 1`, `cooldown` `100 -> 80`. Bias gates the
  taker so it never fights the directional bias.
- **Top-of-book (`k=0`) layer dropped.** No fills observed in `525326`.

**Status.** Not yet uploaded.

## Strategy Active v3 (v2 + aggressive-join probe)

**File:** `src/hydrogel_active_v3.py`.

**Identical to Active v2** plus an explicit aggressive-join probe layer
(Strategy 1):

- When `bias >= 1`, also place a resting buy at `best_bid + 5`
  (about `3` ticks below mid for a `16`-tick spread) for `clip = 6`.
- When `bias >= 2`, tighten to `best_bid + 7` (about `1` tick below
  mid).
- Symmetric for sells.
- Subject to `min_join_edge = 1` tick versus current mid.

**Why a separate version.**

- Historical data shows zero trades at `mid +/- 1`, but the simulator
  allows bots to react to our outstanding quotes. We can't conclude
  from absence in the historical record alone.
- Per-fill PnL at the join layer is much smaller (we sacrifice `~6`
  ticks of edge per unit), so this only pays off if the join layer
  attracts MORE fills than the conservative passive layers.
- The official log will show one of:
  - Join-layer prices fill: aggressive joining works, integrate more
    broadly.
  - Join-layer prices never fill: bots only take at the public bid /
    ask, the previous pessimism was right (for the wrong reason).

**Status.** Not yet uploaded.

## Strategies Discarded by Data

These do not require a probe upload. They are dead by inspection of
historical data.

| Strategy | Reason |
|---|---|
| HYDROGEL ↔ VEV_4000 cross-hedge | Correlation `~0` at every horizon (1, 10, 100, 500, 1000 ticks). Linear-fit residual has near-zero autocorrelation persistence, so no stat-arb signal. |
| Wall-break signal (`>=15` qty drop) | `0` qualifying events in `30,000` historical rows. Small drops (`>=10`) give weak `r100 = -0.18`. Not worth a separate strategy. |
| Wall-imbalance directional bet | All deciles of `bid_wall_qty - ask_wall_qty` show future returns `~0`. No signal. |
| Aggressive join at `mid +/- 1` (unconditional) | Historical bot trades happen at `±7-8` ticks from mid, never at `±1`. Conditional join probe is in `active_v3`; pure unconditional join would just sacrifice spread for the same fills. |

## Strategies Not Yet Implemented

Reasonable to test, deliberately omitted from `active_v3` to keep
upload diffs readable.

5. **Hawkes-style trade clustering.** Count market trades in last `N`
   ticks. After clusters, expect either continuation or mean
   reversion (open question; would need its own probe).
6. **Quote-fade after own toxic fills.** Track our own fills' markouts.
   After consecutive bad-side fills, suspend that side's passive quote
   for `~300` ticks. Defensive; only useful once we have higher fill
   counts than the current `~20` per 1k-tick test.
7. **Volume-pulse sizing.** When recent taker volume is high, increase
   passive clips; when dead, reduce. Sizing tweak; modest expected
   impact.
8. **Order-book wall break.** Discarded above. Wall-imbalance also
   shows no signal in HYDROGEL data.
10. **Adaptive depth based on inventory.** When long-heavy, place more
    aggressive sells (and vice versa). Already partially implemented
    via inventory skew; could be extended to per-level clip sizing,
    but bias-driven `suppress_factor_*` in `active_v2/v3` already
    addresses the same intent.

## Decision

1. Test `active_v2` on the official simulator before chasing more
   ideas, to isolate the effect of bias unification + skew decoupling.
2. Test `active_v3` next to empirically settle the aggressive-join
   question.
3. If either reaches the passive ceiling (`~2k` PnL per 1k-tick test)
   with stable per-day variance, focus shifts to merging HYDROGEL
   logic back into a multi-product trader (vouchers,
   `VELVETFRUIT_EXTRACT`) for portfolio-level PnL — `HYDROGEL` alone
   cannot deliver `5-10x` improvement because the bot-flow ceiling is
   hard.
4. After at least one trending-day test result, decide whether
   Strategies 5 (Hawkes) or 7 (volume-pulse) are worth a probe.
