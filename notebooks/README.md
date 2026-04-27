# Notebooks

Exploratory analysis lives here. The intended loop:

```
data/round-N/  →  notebooks/  →  results/findings_<topic>.md  →  src/trader_<round>.py
```

Each notebook digs into the data, the conclusion is written up under
[`../results/`](../results/), and a `Trader` in
[`../src/`](../src/) cites the finding by filename.

## File format: `.py` cell scripts

Prefer `.py` files with `# %%` cell markers over `.ipynb`. Both
Cursor's Jupyter integration and VS Code render them as notebooks
(Run Cell / Run Above buttons appear), and they diff cleanly in git
without the JSON + base64 image noise. `_template.py` is a starter you
can copy.

`.ipynb` is fine if you want inline images committed; just be aware
diffs will be huge.

## Naming

```
notebooks/<round>__<topic>.py
```

e.g. `tutorial_round.py`, `round-3__fair_price_velvetfruit.py`,
`round-3__voucher_iv_smile.py`. Mirroring the round dir under
[`../data/`](../data/) makes it obvious what dataset a notebook
operates on.

## Imports

Notebooks run from the repo root. They should import the analysis lib
as `from src.analysis import ...`. Run with the venv at `../.venv/`
(matches `../requirements.txt`).
