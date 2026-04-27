# Round datasets

Drop the historical CSVs and any extras IMC publishes per round into the
matching subdirectory:

| Round | Wiki briefing | Data dir |
|---|---|---|
| Tutorial | [`docs/wiki/tutorial-round-simulator-practice/`](../docs/wiki/tutorial-round-simulator-practice/index.md) | `round-tutorial/` |
| Round 1 | [`docs/wiki/round-1-trading-groundwork/`](../docs/wiki/round-1-trading-groundwork/index.md) | `round-1/` |
| Round 2 | [`docs/wiki/round-2-growing-your-outpost/`](../docs/wiki/round-2-growing-your-outpost/index.md) | `round-2/` |
| Round 3 | [`docs/wiki/round-3-gloves-off/`](../docs/wiki/round-3-gloves-off/index.md) | `round-3/` |
| Round 4 | [`docs/wiki/round-4-the-more-the-merrier/`](../docs/wiki/round-4-the-more-the-merrier/index.md) | `round-4/` |

## What goes in each round dir

The Data Capsule on the Prosperity dashboard typically ships:

- `prices_round_<N>_day_<D>.csv` — order-book snapshots per tick.
- `trades_round_<N>_day_<D>.csv` — executed trades per tick.
- A `Wiki_ROUND_<N>_data.zip` referenced from the wiki page (sometimes
  bundles the same CSVs and a notes PDF).

Unzip into the round dir as-is so paths stay predictable for
the analysis notebooks (which load via
[`src/analysis/loaders.py`](../src/analysis/loaders.py)).

## Conventions

- One subdir per round, lower-case, hyphenated. Don't nest by day; the
  filenames already encode the day.
- If you derive a cleaned/aggregated dataset from the raw CSVs (e.g.
  per-product wall-mid series), put it next to the raw files with a
  `derived__` prefix and document how it was built in this README or a
  sibling note.
- Keep the round briefing's `initial_information.md` (or equivalent)
  next to the CSVs if IMC ships one.
