# Prosperity 4 Wiki — local snapshot

This directory is a markdown mirror of the official Prosperity 4 Notion wiki
(<https://imc-prosperity.notion.site/prosperity-4-wiki>). It exists so the
agents working in this repo (and you, offline) can read the rules,
round briefings, and platform contract without leaving the codebase.

## Structure

- `index.md` — root wiki page with links to every section.
- `what-is-prosperity/`, `who-is-imc/`, `storyline/` — competition framing.
- `round-schedule/` — the official CEST timeline for all rounds.
- `game-mechanics-overview/` — how rounds, submissions, and the dashboard work.
- `rules/`, `faq/`, `announcements/` — official rules and live updates.
- `trading-glossary/`, `programming-resources/` — onboarding material.
- `writing-an-algorithm-in-python/` — the `Trader` class contract and
  `TradingState` shape. **This is the main reference for the runtime**;
  `src/datamodel.py` is a local stub of the same types.
- `tutorial-round-…/`, `round-1-…/` … `round-4-…/` — per-round briefings
  (products, position limits, manual trading challenge).

## Refreshing the snapshot

The Notion wiki gets edited during the competition (announcements, FAQ,
round drops). To re-pull from the repo root:

```bash
python3 scripts/fetch_wiki.py docs/wiki
```

The script is dependency-free (stdlib only) and walks the public Notion
page tree via the unofficial `loadPageChunk` endpoint. No auth needed —
the wiki is shared publicly. The root page id is hardcoded in
`scripts/fetch_wiki.py`; if IMC ever moves it, grep `pageId` from a
fresh fetch of `https://imc-prosperity.notion.site/prosperity-4-wiki`.

## Caveats

- Images are linked as `attachment:<uuid>:<name>.png` — they don't resolve
  locally. Open the live wiki if you need a screenshot.
- The fetcher is best-effort markdown conversion: most blocks (text,
  headings, lists, code, tables, callouts) round-trip cleanly, but
  exotic Notion blocks (toggles, embeds, synced blocks) may render as
  plain text. Cross-check the live page if something looks off.
- The repo also contains older standalone copies of two of these pages
  at `src/algorithm_examples.md` and `src/trading_glossary.md`. They
  predate this snapshot and may have hand edits — treat the wiki version
  as the source of truth.
