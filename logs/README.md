# Run logs

The JSON `.log` files Prosperity hands back after a round runs your
`Trader` (download from the Upload & Changelog panel). One subdir per
round, mirroring [`../data/`](../data/). Parse with
[`src/analysis/loaders.py`](../src/analysis/loaders.py)
(`load_log_activities`, `load_log_trades`).

## Filename convention

```
<trader>__<submission_id>.log
```

- `trader` — the source file basename, typically `trader_<round>`.
- `submission_id` — the Prosperity submission id (visible in the
  Upload & Changelog window).

Example:

```
logs/round-tutorial/trader_tutorial__64808.log
```

A matching `.csv`, `.json`, or `.txt` may sit alongside if the run
emitted structured output. Free-form notes go in a sibling
`<basename>.md`.

## Why mirror `data/`?

Pairing each log with the round whose dataset it was tested against
keeps the audit trail tight: when comparing two strategies for a round,
both their inputs (`data/round-N/`) and their outputs (`logs/round-N/`)
live in the same place.
