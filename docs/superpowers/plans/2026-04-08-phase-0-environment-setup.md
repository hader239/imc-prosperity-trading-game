# Phase 0 — Environment Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the repo from "no Python environment" to a clean working virtualenv with a runnable Jupyter notebook in Cursor, ready for Phase 1 data exploration.

**Architecture:** Standard `python -m venv` + `pip install -r requirements.txt`. The analysis notebook is a single file (`notebooks/tutorial_round.ipynb`) with markdown headers per phase, lived-in across multiple sessions. Multi-session state lives in `PROGRESS.md` at the repo root. No package layout (`src/`) is created in this phase — that comes in Phase 5 when we write the `Trader` class.

**Tech Stack:** Python 3.10+, `pandas`, `numpy`, `matplotlib`, `ipykernel`, `jsonpickle`. Notebook execution via Cursor's built-in Jupyter support (no separate JupyterLab install).

**Spec:** `docs/superpowers/specs/2026-04-08-tutorial-round-design.md`

---

## File Structure

**Files to create:**

| Path | Responsibility |
|---|---|
| `requirements.txt` | Pip dependency manifest |
| `notebooks/tutorial_round.ipynb` | Analysis notebook scaffold with phase section headers |
| `PROGRESS.md` | Multi-session "where are we" tracker |

**Files to modify:**

| Path | Change |
|---|---|
| `.gitignore` | Add Python ignores: `.venv/`, `__pycache__/`, `*.pyc`, `.ipynb_checkpoints/` |

**Deferred (NOT created in this phase):**

- `src/trader_tutorial.py` — created in Phase 5
- `src/` directory — git doesn't track empty directories; created when the file is written

---

## Task 1: Pin dependencies in `requirements.txt`

**Files:**
- Create: `requirements.txt`

- [ ] **Step 1: Write the file**

```
# Analysis (used in notebooks)
pandas>=2.2.0
numpy>=1.26.0
matplotlib>=3.8.0

# Notebook kernel for Cursor's Jupyter integration
ipykernel>=6.29.0

# Used by the Trader class for traderData persistence (Phase 5)
jsonpickle>=3.0.0
```

Rationale per package:
- `pandas`, `numpy` — load and process the CSV market data
- `matplotlib` — plot prices, spreads, distributions
- `ipykernel` — provides the Python kernel that Cursor uses to run notebook cells; full `jupyter`/`jupyterlab` is *not* needed because Cursor has its own notebook UI
- `jsonpickle` — serialize the `Trader`'s state into the `traderData` string between simulator ticks (Prosperity allows this library, see `algorithm_examples.md`)

The four other libraries the Prosperity runtime allows (`statistics`, `math`, `typing`) are stdlib and don't go in `requirements.txt`.

- [ ] **Step 2: Verify the file**

Run: `cat requirements.txt`
Expected: the exact content above, no surprise lines.

---

## Task 2: Create and provision the virtualenv

**Files:**
- Create: `.venv/` (gitignored, never committed)

- [ ] **Step 1: Verify Python version is 3.10 or higher**

Run: `python3 --version`
Expected: `Python 3.10.x` or higher (3.11/3.12/3.13 all fine).

If older, install a newer Python (e.g. via `brew install python@3.12` on macOS) before continuing.

- [ ] **Step 2: Create the virtualenv**

Run from project root: `python3 -m venv .venv`
Expected: silent success, a `.venv/` directory now exists.

- [ ] **Step 3: Verify the venv was created**

Run: `ls .venv/bin/python`
Expected: the path exists (no "No such file" error).

- [ ] **Step 4: Install dependencies into the venv**

Run: `.venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt`
Expected: pip upgrade succeeds, then all five packages (plus their transitive deps) install. Last line should look like `Successfully installed ...` with no error markers.

Note: we use `.venv/bin/pip` directly instead of activating the venv, because activation is shell-state that doesn't persist across non-interactive command runs.

- [ ] **Step 5: Verify each direct dependency imports cleanly**

Run:
```bash
.venv/bin/python -c "import pandas, numpy, matplotlib, ipykernel, jsonpickle; print('pandas', pandas.__version__); print('numpy', numpy.__version__); print('matplotlib', matplotlib.__version__); print('jsonpickle', jsonpickle.__version__)"
```
Expected: four version lines, no `ImportError`. Versions should match the `>=` floors in `requirements.txt`.

---

## Task 3: Add Python ignores to `.gitignore`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Read the current file**

Run: `cat .gitignore`
Expected: currently contains only `.superpowers/` (added during brainstorming).

- [ ] **Step 2: Append Python ignores**

Use the Edit tool to change `.gitignore` so the full file content becomes:

```
.superpowers/

# Python
.venv/
__pycache__/
*.pyc
*.pyo

# Jupyter
.ipynb_checkpoints/
```

- [ ] **Step 3: Verify**

Run: `cat .gitignore`
Expected: matches the content above exactly.

Run: `git status --short`
Expected: `.venv/` does NOT appear in the output (it should now be ignored). `.gitignore` should show as modified (`M .gitignore`).

---

## Task 4: Create the notebook scaffold

**Files:**
- Create: `notebooks/tutorial_round.ipynb`

- [ ] **Step 1: Create the `notebooks/` directory**

Run: `mkdir -p notebooks`
Expected: silent success. `ls notebooks` shows an empty directory.

- [ ] **Step 2: Write the notebook file**

Use the Write tool to create `notebooks/tutorial_round.ipynb` with this exact JSON content:

```json
{
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "# Prosperity 4 — Tutorial Round Analysis\n",
    "\n",
    "Companion notebook to `docs/superpowers/specs/2026-04-08-tutorial-round-design.md`.\n",
    "\n",
    "Each section below maps to a phase from the spec. Cells get added as we work through them across multiple sessions."
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## Setup — sanity-check the kernel"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "import pandas as pd\n",
    "import numpy as np\n",
    "import matplotlib.pyplot as plt\n",
    "\n",
    "print(f'pandas {pd.__version__}')\n",
    "print(f'numpy {np.__version__}')\n",
    "print(f'matplotlib {plt.matplotlib.__version__}')"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## Phase 1 — Understand the data format\n",
    "\n",
    "Goal: be able to read any row of the price/trade CSVs and explain what it means."
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## Phase 2 — Characterize each product\n",
    "\n",
    "Goal: a clear picture of how `EMERALDS` and `TOMATOES` behave."
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## Phase 3 — Find tradeable structure\n",
    "\n",
    "Goal: a written hypothesis (\"I think we can make money by …\")."
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## Phase 4 — Design a strategy\n",
    "\n",
    "Goal: a one-page rules spec (when to buy/sell, what size, position management)."
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3 (.venv)",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.10"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 5
}
```

- [ ] **Step 3: Verify the notebook is valid JSON**

Run: `.venv/bin/python -c "import json; json.load(open('notebooks/tutorial_round.ipynb')); print('valid')"`
Expected: prints `valid` with no exception.

- [ ] **Step 4: Verify the notebook can be opened by `nbformat`**

Run: `.venv/bin/python -c "import nbformat; nb = nbformat.read('notebooks/tutorial_round.ipynb', as_version=4); print(f'{len(nb.cells)} cells')"`
Expected: `7 cells` (1 title + 1 setup header + 1 setup code + 4 phase headers).

- [ ] **Step 5: User opens the notebook in Cursor and runs the setup cell**

This is a manual UI step:

1. Open `notebooks/tutorial_round.ipynb` in Cursor.
2. When prompted for a kernel, pick **Python 3 (.venv)** — the one inside the project's `.venv/`. If Cursor doesn't auto-detect it, click "Select Kernel" → "Python Environments" → pick the path ending in `.venv/bin/python`.
3. Click into the **Setup — sanity-check the kernel** code cell and press **Shift+Enter** to run it.

Expected output (versions may be newer):
```
pandas 2.2.x
numpy 2.x.x
matplotlib 3.x.x
```

If this works, the kernel is correctly wired up and Phase 1 can begin in this notebook in any future session.

If it fails: most common cause is the wrong kernel selected. Re-pick it from the kernel selector at the top right of the notebook.

---

## Task 5: Create `PROGRESS.md`

**Files:**
- Create: `PROGRESS.md`

- [ ] **Step 1: Write the file**

Use the Write tool to create `PROGRESS.md` with this content:

```markdown
# Tutorial Round — Progress

> Multi-session tracker for the Prosperity 4 tutorial round work.
> Companion to `docs/superpowers/specs/2026-04-08-tutorial-round-design.md`.

## Where we are

**Currently in:** Phase 0 — Environment setup
**Last session ended at:** Phase 0 environment setup complete.
**Next session starts with:** Phase 1 — load the day -1 prices CSV in the notebook and inspect its structure.

## Phase status

- [x] Phase 0 — Environment setup
- [ ] Phase 1 — Understand the data format
- [ ] Phase 2 — Characterize each product
- [ ] Phase 3 — Find tradeable structure
- [ ] Phase 4 — Design a strategy
- [ ] Phase 5 — Implement the Trader
- [ ] Phase 6 — Submit, observe, iterate

## Open questions / notes

(none yet)

## Concepts covered

(none yet — will be filled as we cover bid/ask, spread, mid-price, market making, etc.)
```

- [ ] **Step 2: Verify**

Run: `cat PROGRESS.md`
Expected: matches the content above.

---

## Task 6: Commit Phase 0 artifacts

**Files:** all of the above

- [ ] **Step 1: Stage the new and modified files**

Run: `git add requirements.txt .gitignore notebooks/tutorial_round.ipynb PROGRESS.md`
Expected: silent success.

- [ ] **Step 2: Verify staging is correct**

Run: `git status --short`
Expected output:
```
A  PROGRESS.md
M  .gitignore
A  notebooks/tutorial_round.ipynb
A  requirements.txt
?? CLAUDE.md
```

The `?? CLAUDE.md` line is the project-instructions file that's intentionally not part of this commit (the user hasn't asked us to commit it).

`.venv/` should NOT appear (gitignored).

- [ ] **Step 3: Commit**

Run:
```bash
git commit -m "chore: set up Python environment and analysis notebook scaffold

Phase 0 of the tutorial round plan: pin pandas/numpy/matplotlib/
ipykernel/jsonpickle in requirements.txt, add a tutorial_round.ipynb
scaffold with phase headers, gitignore Python build artifacts, and
add PROGRESS.md as the multi-session tracker."
```
Expected: commit succeeds, no pre-commit hook errors (none configured yet).

- [ ] **Step 4: Verify**

Run: `git log --oneline -1`
Expected: shows the new commit at HEAD.

Run: `git status --short`
Expected: only `?? CLAUDE.md` remains (the untracked project instructions).

---

## Done state

After all tasks:
- A working `.venv/` with all dependencies installed
- `requirements.txt`, `.gitignore`, `notebooks/tutorial_round.ipynb`, `PROGRESS.md` all committed
- The notebook opens in Cursor and the setup cell runs cleanly against the venv kernel
- `PROGRESS.md` reflects "Phase 0 done, ready for Phase 1"

Phase 1 (the first analysis phase) gets its own plan, written when this one is finished.
