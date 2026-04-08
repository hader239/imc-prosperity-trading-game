# Tutorial Round — Learning Workflow Design

**Date:** 2026-04-08
**Status:** Draft, awaiting user review
**Scope:** IMC Prosperity 4 Tutorial Round (`EMERALDS`, `TOMATOES`)

## What this spec is

A design for the **learning journey** of the tutorial round, not for the trading strategy itself. The strategy is something we will *discover* by analyzing the data together; pre-specifying it would defeat the point.

This spec captures: goals, constraints, the phased roadmap, repo layout, multi-session continuity strategy, and success criteria. The strategy details and the `Trader` class internals are intentionally left as outputs of later phases, not inputs to this spec.

## Goals

1. **Learn the data-to-strategy workflow.** Build the muscle of going from raw market data to a tradeable hypothesis to a working algorithm. This muscle is the actual deliverable — the tutorial-round score is irrelevant.
2. **Produce a submitted `Trader` class** for the tutorial round, derived from observations made in the analysis phases.
3. **Become fluent with the Prosperity framework's quirks** before the real rounds begin (volume sign convention, position-limit rejection semantics, `traderData` persistence, latency budget).

## Constraints

- **Learn by doing.** The user runs the code, makes the observations, and writes the strategy logic. Claude teaches concepts inline, asks what the user observes before stating conclusions, and reviews/explains rather than dumping finished outputs. (See the `feedback_learning_collaboration` memory.)
- **Multi-session.** The work spans multiple working sessions. State must persist between sessions in artifacts, not in conversation context.
- **No prior trading experience.** Order book, market microstructure, and quant concepts are taught from first principles as they come up. The repo's `trading_glossary.md` is the standing reference.
- **No backtesting infrastructure in this round.** The tutorial round is for the workflow itself; we will use the Prosperity simulator (the in-game one) for validation. A local backtester (Jmerle's, used by last year's teams) is a separate project for the real rounds.

## Roadmap (7 phases)

| # | Phase | Outcome |
|---|---|---|
| 0 | Environment setup | Clean repo with a runnable notebook in Cursor |
| 1 | Understand the data format | User can read any CSV row and explain what it means |
| 2 | Characterize each product | A clear picture of how `EMERALDS` and `TOMATOES` behave |
| 3 | Find tradeable structure | A written hypothesis ("I think we can make money by …") |
| 4 | Design a strategy | A one-page strategy spec (rules: when to buy/sell, what size, how to manage position) |
| 5 | Implement the `Trader` | A single Python file ready to upload |
| 6 | Submit, observe, iterate | Submitted tutorial-round algo + a clear sense of the loop to repeat in real rounds |

Phases are sequential. Phase boundaries are natural session-pause points. The analysis phases (1–3) can be revisited mid-implementation if Phase 5/6 surfaces gaps.

### Phase 0 — Environment setup

- Create `.venv` via `python -m venv .venv`, activate it.
- Install `pandas`, `numpy`, `matplotlib`, `jupyter`, `jsonpickle` via `pip`. Pin in `requirements.txt`.
- Verify the Jupyter notebook works inside Cursor.
- Create `notebooks/tutorial_round.ipynb` with section headers for Phases 1–4.

### Phase 1 — Understand the data format

- Load `prices_round_0_day_-1.csv` and `trades_round_0_day_-1.csv` into pandas (semicolon-delimited).
- Inspect: shape, dtypes, columns, head/tail.
- Teach concepts as they appear: order book, bid/ask, mid-price, spread, depth, executed trades vs quotes.
- Sanity-check: how many ticks per day, what timestamp granularity, are products on the same tick grid, what are the volume ranges.

### Phase 2 — Characterize each product

- Plot `mid_price` over time for each product (both days side by side).
- Plot the spread (`ask_price_1 - bid_price_1`) over time.
- Distribution stats: mean, std, min/max for prices, spreads, volumes.
- Look at the trades CSV: what is the bot trade volume, are there any outliers, how do trade prices relate to mid-price.
- Compare the two days for each product: same regime or different?

### Phase 3 — Find tradeable structure

This is a *judgment-heavy* phase, not a recipe. Open questions to investigate:

- Is `EMERALDS` a stable asset around a fair value? If so, what is the fair value, and how tight is it?
- Does `TOMATOES` mean-revert, drift, or random-walk? Over what horizon?
- Are there persistent quote patterns (e.g., a particular bid/ask level always present) that suggest a market maker we can lean on?
- Do trades cluster around certain prices? Do they predict short-term direction?

The output is a **written hypothesis** in the notebook: one or two sentences saying "I think we can extract value by [doing X], because [observation Y]."

### Phase 4 — Design a strategy

Translate the hypothesis into rules. Common shapes for tutorial-round-friendly strategies:

- **Market making around a fair value** (if `EMERALDS` is stable)
- **Mean reversion to a moving average** (if `TOMATOES` mean-reverts)
- **Inventory-skewed market making** (place tighter quotes on the side that reduces inventory)
- **Combinations** (different rules per product)

The output is a one-page rules spec inside the notebook (or a separate Markdown file): triggers, sizes, position management, risk limits.

### Phase 5 — Implement the `Trader`

- Create `src/trader_tutorial.py`.
- Walk through Prosperity framework essentials inline: `run()` signature, `OrderDepth` sign convention, position-limit rejection, `traderData` persistence, latency budget, `bid()` placeholder for Round 2 compatibility.
- User writes the `Trader` class with Claude reviewing each piece. Inventory-management logic is the trickiest part — extra care there.

### Phase 6 — Submit, observe, iterate

- Upload to the Prosperity simulator via the GUI.
- Read the simulator's results. Compare against expectations from Phase 4.
- Identify surprises and decide whether to fix-and-resubmit or accept and move on (the tutorial round doesn't count toward the final score).

## Repo layout

```
imc-prosperity-trading-game/
├── notebooks/
│   └── tutorial_round.ipynb         # analysis (Phases 1-4)
├── src/
│   └── trader_tutorial.py           # Trader class (Phase 5)
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-04-08-tutorial-round-design.md   # this file
├── PROGRESS.md                      # multi-session tracker
├── requirements.txt                 # pip dependencies
├── .venv/                           # virtualenv (gitignored)
├── source_data/...                  # already exists
├── algorithm_examples.md            # already exists
├── trading_glossary.md              # already exists
└── last_year_strat/...              # already exists
```

Naming convention: each round's `Trader` lives in its own `src/trader_<round>.py` file so we keep clean per-round history rather than overwriting.

## Multi-session continuity

The work spans multiple sessions. To make picking-up frictionless:

1. **`PROGRESS.md`** at the repo root — a short, hand-edited tracker. Updated at the end of every working session. Format:
   ```markdown
   # Tutorial Round Progress

   ## Where we are
   Currently in: Phase X — <name>
   Last session ended at: <one-line description>
   Next session starts with: <one-line action>

   ## Phase status
   - [x] Phase 0 — Environment setup
   - [ ] Phase 1 — Understand the data format
   - ...

   ## Open questions / notes
   - ...
   ```

2. **The notebook itself** is a linear record of what we've done — every cell is checked into git.

3. **Memory entries** capture *non-obvious* learnings about the user's workflow preferences and project context (not progress detail — that lives in `PROGRESS.md`).

At the start of each new session, Claude reads `PROGRESS.md` and the notebook's last few cells to re-orient.

## Success criteria

This project succeeds when:

1. The user can independently load and inspect a Prosperity-style CSV in pandas, plot prices, and describe what they see.
2. The user can articulate, in their own words, why their tutorial-round strategy makes sense given the data.
3. A `Trader` class is submitted to the tutorial-round simulator at least once.
4. The user has identified at least one Prosperity framework "gotcha" by hitting it themselves (not just by being told about it).
5. `PROGRESS.md` is up to date and a future session can resume without re-asking "where were we".

The actual *PnL* of the submission is **not** a success criterion. Tutorial round results don't count.

## Out of scope

- Local backtesting infrastructure (Jmerle's backtester, custom dashboards).
- Strategies for products other than `EMERALDS` and `TOMATOES`.
- The Round 1+ product universe (unknown until each round drops).
- Manual trading sub-game (no manual challenge in this round per `initial_information.md`).
- Fancy ML or model-based pricing — out of scope for a first algorithm; if it shows up, it would be a deliberate add-on after a baseline works.

## Open decisions deferred to later phases

- What strategy class to use (Phase 3–4 output).
- Whether to trade both products or just one (Phase 4 decision).
- Specific position limits and risk caps within the 80-unit hard cap (Phase 4).
- Whether `traderData` is needed at all for the tutorial round, or if the Trader can be stateless (Phase 5 decision).
