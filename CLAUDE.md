# CLAUDE.md

Single-page orientation for coding agents picking up this repo. Read the "Documentation map" below, then follow the "Read in order" list before any non-trivial change.

## What this repo is

This is the user's workspace for **Prosperity 4**, IMC Trading's annual
algorithmic-trading competition. The competition runs in 5 rounds: each
round drops a set of products (e.g. EMERALDS, ASH_COATED_OSMIUM,
VELVETFRUIT_EXTRACT, vouchers), the participant uploads a Python
`Trader` class, and the platform runs it against bots for ~10k ticks.
Score = realized + mark-to-market PnL summed across rounds.

The repo is a research + submission workspace, not a library. The
current shape:

- **`src/datamodel.py`** — local stub of the runtime types (`Order`,
  `OrderDepth`, `TradingState`, …) so the editor resolves
  `from datamodel import …` and local analysis can construct fake
  states. **Not** uploaded with submissions; Prosperity ships its own.
- **`src/analysis/`** — small library of CSV/log loaders and the
  fair-value estimators notebooks reach for.
- **`notebooks/`, `data/`, `logs/`, `results/`** — the analysis loop
  (see "Documentation map" below).
- **`src/algorithm_examples.md`, `src/trading_glossary.md`** — older
  standalone copies of two wiki pages, still referenced by some
  comments. Treat the [`docs/wiki/`](./docs/wiki/) snapshot as the
  source of truth.

A trader is a `Trader` class in a single Python file uploaded to the
Prosperity dashboard. New rounds → new `src/trader_<round>.py`. There
are none in the tree yet — earlier ones were removed because they
underperformed.

There is no scraper, server, or build system; everything is plain
Python you can run with the venv at `.venv/`.

## Documentation map

- [`docs/wiki/`](./docs/wiki/) — markdown snapshot of the official
  Prosperity 4 Notion wiki (rules, round briefings, glossary, runtime
  contract). See [`docs/wiki/README.md`](./docs/wiki/README.md) for
  layout.
- [`docs/wiki/writing-an-algorithm-in-python/index.md`](./docs/wiki/writing-an-algorithm-in-python/index.md) —
  the `Trader` class contract and `TradingState` shape. **Single
  source of truth for the runtime API.** Older copies of this and the
  glossary still live at [`src/algorithm_examples.md`](./src/algorithm_examples.md)
  and [`src/trading_glossary.md`](./src/trading_glossary.md); prefer
  the wiki snapshot.
- [`docs/wiki/round-N-…/index.md`](./docs/wiki/) — per-round briefings
  with product list, position limits, and the manual-trading challenge.
- [`scripts/fetch_wiki.py`](./scripts/fetch_wiki.py) — pulls the
  Notion wiki to `docs/wiki/`. Run when announcements/FAQ change or a
  new round drops:
  ```bash
  python3 scripts/fetch_wiki.py docs/wiki
  ```
- [`data/`](./data/) — per-round historical CSVs from the Prosperity
  Data Capsule. One subdir per round (`round-tutorial`, `round-1`, …).
  See [`data/README.md`](./data/README.md) for the file convention.
- [`logs/`](./logs/) — per-round run logs (the JSON files Prosperity
  hands back from the Upload & Changelog panel), mirroring `data/`.
  See [`logs/README.md`](./logs/README.md) for the filename convention
  (`<source>__<trader>__<id>.log`).
- [`src/analysis/`](./src/analysis/) — small library for notebooks:
  `load_prices` / `load_trades` for `data/round-N/` CSVs,
  `load_log_activities` / `load_log_trades` for `.log` JSON, and the
  two fair-value estimators the traders use (`wall_mid`, `microprice`).
- [`notebooks/`](./notebooks/) — exploratory analysis. Cell-script
  `.py` files with `# %%` markers (renders as a notebook in Cursor /
  VS Code, diffs cleanly). Start from
  [`notebooks/_template.py`](./notebooks/_template.py).
- [`results/`](./results/) — markdown write-ups
  (`findings_<topic>.md`) referenced from trader docstrings. See
  [`results/README.md`](./results/README.md) for the format.

## Read in order (agent onboarding)

Before any non-trivial change to a `Trader`:

1. [`docs/wiki/what-is-prosperity/index.md`](./docs/wiki/what-is-prosperity/index.md) — what the competition is.
2. [`docs/wiki/game-mechanics-overview/index.md`](./docs/wiki/game-mechanics-overview/index.md) — rounds, submissions, scoring.
3. [`docs/wiki/writing-an-algorithm-in-python/index.md`](./docs/wiki/writing-an-algorithm-in-python/index.md) — `Trader.run()` contract, `TradingState`, position limits, `traderData` persistence.
4. [`src/datamodel.py`](./src/datamodel.py) — confirm the local types match the contract above.
5. The current round's wiki page (e.g. [`docs/wiki/round-3-gloves-off/index.md`](./docs/wiki/round-3-gloves-off/index.md)) — products in scope and their limits.
6. Any existing `src/trader_<round>.py` file (none yet) plus
   [`results/`](./results/) findings notes for the products in scope.

If a round just opened and the wiki snapshot looks stale, refresh with
`python3 scripts/fetch_wiki.py docs/wiki` before reading.

## Behavioral guidelines

Guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.