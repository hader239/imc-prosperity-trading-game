# Round 4 Mark 14 / Mark 38 Liquidity Edge

## Question

Can we exploit the `Mark 14` versus `Mark 38` flow in `HYDROGEL_PACK` and `VEV_4000` by replacing `Mark 14` as top-of-book liquidity?

## Analysis

Historical round-4 day-3 data showed that `Mark 14`'s profitability in `HYDROGEL_PACK` and `VEV_4000` was not directional. It came from execution: `Mark 14` repeatedly bought at best bid and sold at best ask against `Mark 38`.

Historical same-timestamp edge:

- `HYDROGEL_PACK`: `Mark 14` averaged about `+8.0` ticks per unit versus mid, across `1,003` `Mark 14`/`Mark 38` trades.
- `VEV_4000`: `Mark 14` averaged about `+10.4` ticks per unit versus mid, across `439` `Mark 14`/`Mark 38` trades.
- Future direction after those trades was near coin-flip, so following `Mark 14` after seeing a trade is not the edge.

Official backtester validation used `src/trader_mark14_liquidity_probe.py`.

Small one-tick probe, `logs/522985.log`:

- Quoted `best_bid + 1` and `best_ask - 1`.
- Total marked PnL: `+310.5`.
- `HYDROGEL_PACK`: `+212.0`.
- `VEV_4000`: `+98.5`.
- All fills were against `Mark 38`.

Scaled one-tick probe, `logs/523131.log`:

- Same one-tick pricing, larger clips/caps.
- Total marked PnL: `+845.0`.
- `HYDROGEL_PACK`: `+642.0`, ending position `+18`.
- `VEV_4000`: `+203.0`, ending position `-4`.
- Same number of fill events as the small probe, but larger filled quantities.

Two-tick probe, `logs/523323.log`:

- Quoted `best_bid + 2` and `best_ask - 2`.
- Total marked PnL: `+1026.0`.
- `HYDROGEL_PACK`: `+841.0`, ending position `+1`.
- `VEV_4000`: `+185.0`, ending position `-4`.
- All fills were still against `Mark 38`.

Comparison:

| Version | Total PnL | HYDROGEL PnL | VEV_4000 PnL | HYDROGEL End Pos | VEV_4000 End Pos |
|---|---:|---:|---:|---:|---:|
| Small 1-tick | 310.5 | 212.0 | 98.5 | 14 | -1 |
| Scaled 1-tick | 845.0 | 642.0 | 203.0 | 18 | -4 |
| Scaled 2-tick | 1026.0 | 841.0 | 185.0 | 1 | -4 |

The `2`-tick version improved `HYDROGEL_PACK` because it left much less stale inventory. It slightly hurt `VEV_4000`, where fill volume did not improve and the strategy simply gave up one extra tick of edge.

There is no evidence that `Mark 14` adapts. In the small and scaled one-tick logs, the historical `Mark 14`/`Mark 38` trades disappear and are replaced by `SUBMISSION`/`Mark 38` trades at the same timestamps. In the two-tick log, `28` of `31` historical `HYDROGEL_PACK` `Mark 14`/`Mark 38` trades and all `9` `VEV_4000` trades were replaced. The remaining `HYDROGEL_PACK` trades stayed with `Mark 14` because our quote logic did not intercept them.

## Decision

Use `Mark 14`/`Mark 38` as a liquidity-replacement module, not a directional signal.

Recommended parameters:

1. `HYDROGEL_PACK`: quote `2` ticks inside the spread, clip `6`, test cap around `100`, minimum edge `5` ticks, inventory skew `0.08`.
2. `VEV_4000`: quote `1` tick inside the spread, clip `3`, test cap around `60`, minimum edge `7` ticks, inventory skew `0.15`.
3. Only quote when the proposed bid/ask still has enough edge versus current mid after inventory skew.
4. Expect fills against `Mark 38`; if future logs show fills against other bots with worse markouts, add counterparty-specific filtering if possible from `own_trades`.

The core assumption is validated: `Mark 38` is deterministic liquidity-taking flow, and we can replace `Mark 14` at the top of book to capture the spread.
