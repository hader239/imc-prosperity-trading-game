# Round 4 Counterparty Findings

## Question

Which named counterparties in Round 4 look strong, repetitive, or directional, and does that conclusion hold when each bot is split by product?

## Reproducible Inputs

Data used:

- `data/round-4/trades_round_4_day_1.csv` through `day_3`, with named buyers and sellers.
- `data/round-4/prices_round_4_day_1.csv` through `day_3`, for contemporaneous, past, future, and end-of-day mids.
- `data/round-3/trades_round_3_day_0.csv` through `day_2`, as anonymous same-product history for the repeated basket-flow sanity check.

Script-backed outputs:

- `scripts/analyze_round4_counterparties.py` computes the product-level and pair-level metrics.
- `results/round4_counterparty_product_metrics.md` contains the full per-bot, per-product table, including all horizons previously computed for `Mark 67`.
- `results/round4_counterparty_product_metrics.csv` and `results/round4_counterparty_pair_metrics.csv` contain the same data in machine-readable form.

Definitions:

- `EOD PnL`: trade marked from execution price to same-day closing mid, from the bot's side.
- `Edge`: trade marked from execution price to same-tick mid, from the bot's side.
- `Past 1k`: volume-weighted signed move over the previous 1,000 ticks; negative for a buyer means it bought after a drawdown.
- `F1k` / `F10k`: volume-weighted signed future mid move after 1,000 / 10,000 ticks. Positive means the market moved in the bot's trade direction.
- `H1k%` / `H10k%`: volume-weighted hit rate for the same future horizon.
- `P100` / `P500` / `P1k` / `P5k` / `P10k`: total execution-to-future-mid PnL after that tick window. Buys use `(future_mid - trade_price) * quantity`; sells use `(trade_price - future_mid) * quantity`.

Future horizons are clipped to the last tick of the same day and past horizons are clipped to the first tick of the same day. This matches the original `Mark 67` calculation.

## Bot Strength

Estimated PnL marks each named bot's historical trades to the end-of-day mid for each product/day. This is not platform-realized PnL, but it is a useful zero-sum proxy for who bought before end marks rose or sold before they fell.

| Bot | EOD PnL | Trades | Volume | Edge | Main source |
|---|---:|---:|---:|---:|---|
| `Mark 14` | 42,205.5 | 2,172 | 8,718 | 49,897.0 | `HYDROGEL_PACK`, `VEV_4000` |
| `Mark 67` | 27,261.0 | 165 | 1,510 | -1,156.5 | `VELVETFRUIT_EXTRACT` |
| `Mark 01` | 10,100.5 | 1,843 | 7,428 | 9,975.0 | `VELVETFRUIT_EXTRACT`, vouchers |
| `Mark 55` | -13,204.0 | 1,198 | 6,551 | -16,222.5 | `VELVETFRUIT_EXTRACT` |
| `Mark 49` | -15,346.0 | 122 | 1,186 | 861.5 | `VELVETFRUIT_EXTRACT` |
| `Mark 22` | -17,395.0 | 1,584 | 5,889 | -1,929.5 | `VELVETFRUIT_EXTRACT`, vouchers |
| `Mark 38` | -33,622.0 | 1,478 | 5,000 | -41,425.0 | `HYDROGEL_PACK`, `VEV_4000` |

Substantial bot/product splits, filtering out rows below 100 volume:

| Bot | Product | Vol | Buy | Sell | EOD PnL | Edge | Past 1k | P100 | P500 | P1k | P5k | P10k | F1k | H1k% | F10k | H10k% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `Mark 01` | `VELVETFRUIT_EXTRACT` | 2,792 | 1,417 | 1,375 | 4,366.5 | 7,345.0 | -0.341 | 7,986.5 | 7,784.5 | 8,137.0 | 7,375.5 | 6,035.0 | 0.284 | 49.0 | -0.469 | 48.4 |
| `Mark 01` | `VEV_5300` | 439 | 439 | 0 | 1,755.0 | 399.0 | 0.048 | 350.0 | 341.5 | 336.5 | 402.5 | 513.0 | -0.142 | 32.1 | 0.260 | 50.3 |
| `Mark 01` | `VEV_5400` | 911 | 911 | 0 | 1,882.0 | 544.5 | -0.037 | 517.5 | 535.5 | 549.0 | 686.0 | 635.0 | 0.005 | 24.8 | 0.099 | 45.1 |
| `Mark 01` | `VEV_5500` | 1,042 | 1,042 | 0 | 837.0 | 547.5 | 0.003 | 526.5 | 531.5 | 532.5 | 580.0 | 546.5 | -0.014 | 7.5 | -0.001 | 25.0 |
| `Mark 01` | `VEV_6000` | 1,105 | 1,105 | 0 | 552.5 | 552.5 | 0.000 | 552.5 | 552.5 | 552.5 | 552.5 | 552.5 | 0.000 | 0.0 | 0.000 | 0.0 |
| `Mark 01` | `VEV_6500` | 1,105 | 1,105 | 0 | 552.5 | 552.5 | 0.000 | 552.5 | 552.5 | 552.5 | 552.5 | 552.5 | 0.000 | 0.0 | 0.000 | 0.0 |
| `Mark 14` | `HYDROGEL_PACK` | 4,022 | 1,989 | 2,033 | 24,415.0 | 32,006.0 | -0.305 | 32,758.5 | 32,649.0 | 32,278.5 | 34,581.0 | 33,617.0 | 0.068 | 47.6 | 0.401 | 48.2 |
| `Mark 14` | `VELVETFRUIT_EXTRACT` | 3,524 | 1,761 | 1,763 | 6,906.0 | 8,595.0 | 0.029 | 8,109.0 | 8,088.0 | 7,630.5 | 5,922.5 | 4,121.0 | -0.274 | 39.7 | -1.270 | 42.7 |
| `Mark 14` | `VEV_4000` | 870 | 458 | 412 | 9,241.0 | 9,059.5 | 0.024 | 9,033.5 | 8,916.5 | 8,999.5 | 8,973.0 | 9,109.0 | -0.069 | 42.5 | 0.057 | 47.6 |
| `Mark 14` | `VEV_5200` | 122 | 122 | 0 | 973.5 | 122.0 | 0.705 | 133.5 | 86.0 | 99.0 | 110.5 | 81.0 | -0.189 | 36.9 | -0.336 | 49.2 |
| `Mark 14` | `VEV_5300` | 105 | 105 | 0 | 742.0 | 79.5 | 0.524 | 53.0 | 31.0 | 62.0 | 142.5 | 149.0 | -0.167 | 33.3 | 0.662 | 53.3 |
| `Mark 22` | `VELVETFRUIT_EXTRACT` | 843 | 146 | 697 | -9,983.5 | 577.5 | 1.378 | -476.5 | -515.0 | -380.5 | -650.5 | 541.0 | -1.136 | 32.3 | -0.043 | 49.6 |
| `Mark 22` | `VEV_5200` | 162 | 3 | 159 | -1,123.0 | -151.5 | -0.583 | -168.0 | -113.0 | -161.0 | -210.0 | -218.5 | -0.059 | 52.5 | -0.414 | 45.1 |
| `Mark 22` | `VEV_5300` | 548 | 3 | 545 | -2,514.0 | -476.5 | -0.141 | -403.5 | -369.5 | -394.0 | -533.0 | -651.5 | 0.151 | 41.8 | -0.319 | 41.2 |
| `Mark 22` | `VEV_5400` | 959 | 0 | 959 | -1,798.0 | -566.0 | 0.012 | -523.5 | -537.5 | -545.0 | -669.0 | -619.0 | 0.022 | 26.0 | -0.055 | 39.0 |
| `Mark 22` | `VEV_5500` | 1,069 | 0 | 1,069 | -849.0 | -561.0 | -0.015 | -533.5 | -536.0 | -541.0 | -580.5 | -543.0 | 0.019 | 9.6 | 0.017 | 24.5 |
| `Mark 22` | `VEV_6000` | 1,105 | 0 | 1,105 | -552.5 | -552.5 | 0.000 | -552.5 | -552.5 | -552.5 | -552.5 | -552.5 | 0.000 | 0.0 | 0.000 | 0.0 |
| `Mark 22` | `VEV_6500` | 1,105 | 0 | 1,105 | -552.5 | -552.5 | 0.000 | -552.5 | -552.5 | -552.5 | -552.5 | -552.5 | 0.000 | 0.0 | 0.000 | 0.0 |
| `Mark 38` | `HYDROGEL_PACK` | 4,096 | 2,065 | 2,031 | -24,392.0 | -32,291.0 | 0.233 | -32,815.5 | -32,716.5 | -32,289.5 | -34,466.0 | -33,745.0 | 0.000 | 47.5 | -0.355 | 50.0 |
| `Mark 38` | `VEV_4000` | 876 | 415 | 461 | -9,240.5 | -9,091.0 | -0.057 | -9,027.5 | -8,928.5 | -9,020.5 | -9,019.0 | -9,139.0 | 0.080 | 46.0 | -0.055 | 48.6 |
| `Mark 49` | `VELVETFRUIT_EXTRACT` | 1,186 | 115 | 1,071 | -15,346.0 | 861.5 | 1.724 | -1,404.0 | -1,355.5 | -1,696.5 | -1,189.5 | -1,588.5 | -2.157 | 16.9 | -2.066 | 39.6 |
| `Mark 55` | `VELVETFRUIT_EXTRACT` | 6,551 | 3,254 | 3,297 | -13,204.0 | -16,222.5 | 0.082 | -16,082.5 | -15,797.5 | -15,866.5 | -13,204.0 | -10,562.5 | 0.054 | 47.7 | 0.864 | 52.5 |
| `Mark 67` | `VELVETFRUIT_EXTRACT` | 1,510 | 1,510 | 0 | 27,261.0 | -1,156.5 | -1.915 | 1,867.5 | 1,795.5 | 2,176.0 | 1,746.0 | 1,454.0 | 2.207 | 74.6 | 1.729 | 55.3 |

## Product-Level Interpretation

`VELVETFRUIT_EXTRACT` is the only product with a clean directional counterparty signal. `Mark 67` buys only this product, buys after a recent negative move, loses on same-tick edge, and is followed by a strong rebound: +2.207 at 1,000 ticks with a 74.6% volume-weighted hit rate. Its execution-to-1,000-tick PnL is +2,176.0, much smaller than its EOD PnL because the EOD mark captures the full day rebound. `Mark 49` is the cleanest fade: mostly seller volume, -2.157 at 1,000 ticks, only 16.9% hit rate, and -1,696.5 PnL at 1,000 ticks.

`Mark 22` is also weak in `VELVETFRUIT_EXTRACT`, but less clean than `Mark 49`: its 1,000-tick signal is bad (-1.136), while the 10,000-tick signal is nearly flat (-0.043). Treat it as a short-horizon fade, not a standalone long-horizon oracle.

`Mark 55` has the largest `VELVETFRUIT_EXTRACT` volume and a positive 10,000-tick signed move (+0.864), but it loses heavily on EOD PnL, same-tick edge, and window PnL (-15,866.5 at 1,000 ticks, -10,562.5 at 10,000 ticks). It is too mixed to follow by itself.

`Mark 14` is the strongest participant overall, but the product split shows why it should not be copied blindly. Its edge is concentrated in `HYDROGEL_PACK` and `VEV_4000`; its `VELVETFRUIT_EXTRACT` future signal is negative (-1.270 at 10,000 ticks), while still profitable on window PnL because its execution edge is so large.

`HYDROGEL_PACK` and `VEV_4000` are mostly a `Mark 14` versus `Mark 38` execution/relative-value story. `Mark 14` wins +24,415 on `HYDROGEL_PACK` and +9,241 on `VEV_4000`; `Mark 38` loses almost the mirror image. The window PnL is already strongly positive for `Mark 14` by 1,000 ticks (+32,278.5 on `HYDROGEL_PACK`, +8,999.5 on `VEV_4000`), but the future-direction hit rates are near coin flip, so this is not a simple "follow the last trade" signal.

The voucher basket signal is repetitive but not strongly directional. `Mark 01` buys `VEV_5300` through `VEV_6500` from `Mark 22`; `VEV_6000` and `VEV_6500` are mechanically pinned in the historical data, so their future-move columns are zero. The more useful basket components are `VEV_5300` to `VEV_5500`, and only when independent fair value says the basket is cheap.

## Pair Breakdown

Important pair rows, all from the generated pair metrics:

| Bot | Product | Side | Counterparty | Vol | EOD PnL | Edge | P1k | F1k | H1k% | P10k | F10k | H10k% |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `Mark 67` | `VELVETFRUIT_EXTRACT` | BUY | `Mark 49` | 963 | 15,890.0 | -612.0 | 1,551.0 | 2.246 | 72.4 | 1,531.5 | 2.226 | 56.7 |
| `Mark 67` | `VELVETFRUIT_EXTRACT` | BUY | `Mark 22` | 546 | 11,380.0 | -546.0 | 619.5 | 2.135 | 78.4 | -98.0 | 0.821 | 52.7 |
| `Mark 49` | `VELVETFRUIT_EXTRACT` | SELL | `Mark 67` | 963 | -15,890.0 | 612.0 | -1,551.0 | -2.246 | 13.9 | -1,531.5 | -2.226 | 39.3 |
| `Mark 14` | `HYDROGEL_PACK` | BUY | `Mark 38` | 1,989 | 40,128.0 | 15,876.5 | 16,198.0 | 0.162 | 46.7 | 17,016.0 | 0.573 | 48.9 |
| `Mark 14` | `HYDROGEL_PACK` | SELL | `Mark 38` | 2,033 | -15,713.0 | 16,129.5 | 16,080.5 | -0.024 | 48.5 | 16,601.0 | 0.232 | 47.5 |
| `Mark 14` | `VEV_4000` | BUY | `Mark 38` | 458 | 11,631.5 | 4,795.5 | 4,821.0 | 0.056 | 44.3 | 4,715.0 | -0.176 | 45.6 |
| `Mark 38` | `HYDROGEL_PACK` | SELL | `Mark 14` | 1,989 | -40,128.0 | -15,876.5 | -16,198.0 | -0.162 | 48.8 | -17,016.0 | -0.573 | 49.5 |
| `Mark 01` | `VEV_5300` | BUY | `Mark 22` | 439 | 1,755.0 | 399.0 | 336.5 | -0.142 | 32.1 | 513.0 | 0.260 | 50.3 |
| `Mark 01` | `VEV_5400` | BUY | `Mark 22` | 911 | 1,882.0 | 544.5 | 549.0 | 0.005 | 24.8 | 635.0 | 0.099 | 45.1 |
| `Mark 01` | `VEV_5500` | BUY | `Mark 22` | 1,042 | 837.0 | 547.5 | 532.5 | -0.014 | 7.5 | 546.5 | -0.001 | 25.0 |

## Repetitive Flow

Round 4 day 1 and day 2 trade streams exactly match Round 3 day 1 and day 2 after stripping buyer/seller IDs. Round 3 day 0 also has the same repeated voucher basket structure, so these counterparty patterns likely existed before names were revealed.

`Mark 01` and `Mark 22` are the clearest repetitive pair. `Mark 01` buys simultaneous baskets of low-value vouchers from `Mark 22`:

- 140 events of exactly `VEV_5400`, `VEV_5500`, `VEV_6000`, `VEV_6500` together, average total quantity 14.1.
- 101 events of exactly `VEV_5300`, `VEV_5400`, `VEV_5500`, `VEV_6000`, `VEV_6500` together, average total quantity 16.9.
- Exact repeated basket examples include 39 events of quantity 5 in all four of `VEV_5400`, `VEV_5500`, `VEV_6000`, `VEV_6500`; 38 events of quantity 2 in the same four; 35 events of quantity 4 in the same four.
- Round 3 day 0 anonymously shows the same basket family: repeated simultaneous trades in `VEV_5400`, `VEV_5500`, `VEV_6000`, `VEV_6500` with equal quantities 2, 3, 4, or 5.

`Mark 14` and `Mark 38` are the second major repetitive pair:

- They trade `HYDROGEL_PACK` and `VEV_4000` against each other constantly, mostly single-product clips of 2 to 6 units for `HYDROGEL_PACK` and 1 to 3 units for `VEV_4000`.
- Despite two-way flow, `Mark 14` wins heavily and `Mark 38` loses heavily, so the exploitable signal is likely execution/relative-value edge, not the mere existence of their pair trade.

## Decision

Priority live hypotheses to test:

1. Follow `Mark 67` in `VELVETFRUIT_EXTRACT`: if a market trade has buyer `Mark 67`, buy up to a small fixed inventory cap and unwind after a short horizon or when mid reverts by about 2 ticks.
2. Fade `Mark 49` in `VELVETFRUIT_EXTRACT`: if seller is `Mark 49`, buy; if buyer is `Mark 49`, avoid buying and consider a small short/reduction.
3. Treat `Mark 22` selling `VELVETFRUIT_EXTRACT` as a weaker short-horizon fade, especially when paired with `Mark 67` as buyer.
4. Do not copy `Mark 14` in `VELVETFRUIT_EXTRACT`. Use `Mark 14` mainly as a warning that `HYDROGEL_PACK` and `VEV_4000` trades against `Mark 38` contain execution/relative-value information.
5. Track `Mark 01` voucher baskets from `Mark 22`, but only join the `Mark 01` side when independent voucher fair value says `VEV_5300` to `VEV_5500` are cheap. Do not give much weight to `VEV_6000` or `VEV_6500` alone.

Suggested validation upload:

- Build a deliberately simple `VELVETFRUIT_EXTRACT` counterparty test trader.
- Rule A: buy small when `Mark 67` is buyer or `Mark 49` is seller.
- Rule B: sell/reduce when `Mark 49` is buyer, after a fixed holding timeout, or after a roughly 2 tick rebound.
- Rule C: cap inventory tightly, for example 40 to 80 units, so the returned log isolates signal quality rather than inventory blow-up.
- After submission, compare fills and PnL around `Mark 67`/`Mark 49` events to the historical +2 tick rebound assumption.
