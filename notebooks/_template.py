# %%
"""Starter notebook — copy this when starting a new round/topic.

Run from the repo root with the venv at .venv/ active. Each `# %%`
block is a cell in Cursor / VS Code's Jupyter view.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

import sys
sys.path.insert(0, str(Path.cwd()))  # so `from src.analysis import ...` works

from src.analysis import (
    load_log_activities,
    load_prices,
    load_trades,
    microprice,
    wall_mid,
)

# %% [markdown]
# ## Load a round's historical CSVs
# Drop the prices_round_*_day_*.csv / trades_round_*_day_*.csv into
# `data/round-N/` first.

# %%
ROUND_DIR = Path("data/round-tutorial")  # change me
prices = load_prices(ROUND_DIR)
trades = load_trades(ROUND_DIR)
prices.head()

# %%
# One product at a time is usually what you want.
PRODUCT = prices["product"].unique()[0]
p = prices[prices["product"] == PRODUCT].copy()
p["wall_mid"] = wall_mid(p)
p["microprice"] = microprice(p)

# %% [markdown]
# ## Quick price plot

# %%
fig, ax = plt.subplots(figsize=(12, 4))
ax.plot(p["timestamp"], p["mid_price"], label="mid", lw=0.6, alpha=0.6)
ax.plot(p["timestamp"], p["wall_mid"], label="wall_mid", lw=0.8)
ax.plot(p["timestamp"], p["microprice"], label="microprice", lw=0.6, alpha=0.6)
ax.set(title=f"{PRODUCT} — mid vs wall_mid vs microprice", xlabel="timestamp")
ax.legend()
plt.show()

# %% [markdown]
# ## Replay log analysis (optional)
# After running a Trader on the platform, drop the `.log` JSON into
# `logs/round-N/` and load it like this.

# %%
# log_path = Path("logs/round-tutorial/platform__tutorial__64808.log")
# acts = load_log_activities(log_path)
# my_trades = load_log_trades(log_path)
# my_trades = my_trades[
#     (my_trades["buyer"] == "SUBMISSION") | (my_trades["seller"] == "SUBMISSION")
# ]
