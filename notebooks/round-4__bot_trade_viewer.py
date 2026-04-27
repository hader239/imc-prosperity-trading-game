# %%
"""Round 4 bot trade viewer.

Run from the repo root. Cursor / VS Code render each `# %%` block as a
notebook cell.

Use this to inspect:
- Round 4 historical bot-vs-bot trades from `data/round-4/`.
- A downloaded Prosperity `.log` file, including SUBMISSION fills.
"""

from pathlib import Path
from typing import Iterable, Optional
import re
import sys

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path.cwd()))

from src.analysis import load_log_activities, load_log_trades, load_prices, load_trades


# %% [markdown]
# ## Configuration
#
# Start with the round 4 data capsule. To inspect an official backtester log,
# set `LOG_PATH` to the downloaded `.log` file and run the log-loading cell
# below.

# %%
ROUND_DIR = Path("data/round-4")
LOG_PATH: Optional[Path] = None
# Example:
# LOG_PATH = Path("logs/round-4/trader_mark67_probe__YOUR_SUBMISSION_ID.log")


# %% [markdown]
# ## Loading Helpers

# %%
def _day_from_source(value: object) -> Optional[int]:
    match = re.search(r"day_(-?\d+)", str(value))
    return int(match.group(1)) if match else None


def normalize_prices(prices: pd.DataFrame) -> pd.DataFrame:
    prices = prices.copy()
    if "day" not in prices.columns:
        prices["day"] = prices.get("_source", "").map(_day_from_source).fillna(0)
    prices["day"] = prices["day"].astype(int)
    prices["timestamp"] = prices["timestamp"].astype(int)
    prices["mid_price"] = prices["mid_price"].astype(float)
    prices["product"] = prices["product"].astype(str)
    return prices.sort_values(["day", "product", "timestamp"], kind="stable")


def normalize_trades(trades: pd.DataFrame) -> pd.DataFrame:
    trades = trades.copy()
    if trades.empty:
        return pd.DataFrame(
            columns=["day", "timestamp", "buyer", "seller", "symbol", "price", "quantity"]
        )

    if "symbol" not in trades.columns and "product" in trades.columns:
        trades["symbol"] = trades["product"]

    if "day" not in trades.columns:
        if "_source" in trades.columns:
            trades["day"] = trades["_source"].map(_day_from_source).fillna(0)
        else:
            trades["day"] = 0

    for col in ("buyer", "seller"):
        if col not in trades.columns:
            trades[col] = ""
        trades[col] = trades[col].fillna("").astype(str)

    trades["day"] = trades["day"].astype(int)
    trades["timestamp"] = trades["timestamp"].astype(int)
    trades["symbol"] = trades["symbol"].astype(str)
    trades["price"] = trades["price"].astype(float)
    trades["quantity"] = trades["quantity"].astype(int)
    return trades.sort_values(["day", "symbol", "timestamp"], kind="stable")


def load_capsule(round_dir: Path = ROUND_DIR, days: Optional[Iterable[int]] = None):
    prices = normalize_prices(load_prices(round_dir, days=days))
    trades = normalize_trades(load_trades(round_dir, days=days))
    return prices, trades


def load_log(log_path: Path):
    prices = normalize_prices(load_log_activities(log_path))
    trades = normalize_trades(load_log_trades(log_path))
    return prices, trades


def available_bots(trades: pd.DataFrame) -> list[str]:
    if trades.empty:
        return []
    bots = set(trades["buyer"].dropna()) | set(trades["seller"].dropna())
    return sorted(bot for bot in bots if bot)


def available_products(prices: pd.DataFrame) -> list[str]:
    return sorted(prices["product"].dropna().unique().tolist())


def available_days(prices: pd.DataFrame) -> list[int]:
    return sorted(prices["day"].dropna().astype(int).unique().tolist())


# %% [markdown]
# ## Load Round 4 Historical Data

# %%
prices, trades = load_capsule()
print(f"Loaded prices: {prices.shape}, trades: {trades.shape}")
print("Products:", available_products(prices))
print("Days:", available_days(prices))
print("Bots:", available_bots(trades))


# %% [markdown]
# ## Optional: Load an Official Backtester Log
#
# Set `LOG_PATH` above, then run this cell. It replaces `prices` and `trades`
# with data from the log.

# %%
if LOG_PATH is not None:
    prices, trades = load_log(LOG_PATH)
    print(f"Loaded log prices: {prices.shape}, trades: {trades.shape}")
    print("Products:", available_products(prices))
    print("Days:", available_days(prices))
    print("Bots:", available_bots(trades))


# %% [markdown]
# ## Plot Function
#
# Selected bots are plotted twice if they are both buyer and seller in the
# filtered trades: upward markers for their buys, downward markers for their
# sells. Use `include_background_trades=True` to show all trades as faint dots.

# %%
def plot_product_trades(
    prices: pd.DataFrame,
    trades: pd.DataFrame,
    product: str,
    day: Optional[int] = None,
    bots: Optional[Iterable[str]] = None,
    window: Optional[tuple[int, int]] = None,
    include_background_trades: bool = True,
    annotate: bool = False,
    figsize: tuple[int, int] = (14, 6),
) -> pd.DataFrame:
    bots = list(bots or [])

    px = prices[prices["product"] == product].copy()
    tr = trades[trades["symbol"] == product].copy()
    if day is not None:
        px = px[px["day"] == day]
        tr = tr[tr["day"] == day]
    if window is not None:
        start, end = window
        px = px[(px["timestamp"] >= start) & (px["timestamp"] <= end)]
        tr = tr[(tr["timestamp"] >= start) & (tr["timestamp"] <= end)]

    if px.empty:
        raise ValueError(f"No prices found for product={product!r}, day={day!r}")

    fig, ax = plt.subplots(figsize=figsize)
    for px_day, group in px.groupby("day", sort=True):
        label = f"mid day {px_day}" if day is None else "mid"
        ax.plot(group["timestamp"], group["mid_price"], lw=0.9, label=label)

    if include_background_trades and not tr.empty:
        ax.scatter(
            tr["timestamp"],
            tr["price"],
            s=(tr["quantity"].clip(lower=1) * 5),
            c="lightgray",
            alpha=0.35,
            label="all trades",
            zorder=2,
        )

    selected_rows = []
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    for idx, bot in enumerate(bots):
        color = colors[idx % len(colors)]
        buys = tr[tr["buyer"] == bot]
        sells = tr[tr["seller"] == bot]

        if not buys.empty:
            selected_rows.append(buys.assign(selected_bot=bot, selected_side="BUY"))
            ax.scatter(
                buys["timestamp"],
                buys["price"],
                s=(buys["quantity"].clip(lower=1) * 16),
                marker="^",
                color=color,
                edgecolors="black",
                linewidths=0.4,
                label=f"{bot} buys",
                zorder=4,
            )
            if annotate:
                for _, row in buys.iterrows():
                    ax.annotate(bot, (row["timestamp"], row["price"]), fontsize=7)

        if not sells.empty:
            selected_rows.append(sells.assign(selected_bot=bot, selected_side="SELL"))
            ax.scatter(
                sells["timestamp"],
                sells["price"],
                s=(sells["quantity"].clip(lower=1) * 16),
                marker="v",
                color=color,
                edgecolors="black",
                linewidths=0.4,
                label=f"{bot} sells",
                zorder=4,
            )
            if annotate:
                for _, row in sells.iterrows():
                    ax.annotate(bot, (row["timestamp"], row["price"]), fontsize=7)

    title_day = "all days" if day is None else f"day {day}"
    ax.set_title(f"{product} price and selected bot trades ({title_day})")
    ax.set_xlabel("timestamp")
    ax.set_ylabel("price")
    ax.grid(alpha=0.2)
    ax.legend(loc="best")
    plt.show()

    if not selected_rows:
        return pd.DataFrame()

    selected = pd.concat(selected_rows, ignore_index=True)
    return selected.sort_values(["day", "timestamp", "selected_bot", "selected_side"])


# %% [markdown]
# ## Manual Viewer
#
# Edit these values and rerun the cell.

# %%
PRODUCT = "VELVETFRUIT_EXTRACT"
DAY = 1
BOTS = ["Mark 67"]
WINDOW = None
# WINDOW = (0, 120_000)

selected = plot_product_trades(
    prices,
    trades,
    product=PRODUCT,
    day=DAY,
    bots=BOTS,
    window=WINDOW,
    include_background_trades=True,
)
selected.head(20)


# %% [markdown]
# ## Mark 67 Focus View

# %%
mark67 = plot_product_trades(
    prices,
    trades,
    product="VELVETFRUIT_EXTRACT",
    day=DAY,
    bots=["Mark 67", "Mark 49", "Mark 22"],
    include_background_trades=True,
)
mark67[["day", "timestamp", "selected_bot", "selected_side", "buyer", "seller", "price", "quantity"]].head(30)


# %% [markdown]
# ## Optional Widget Viewer
#
# This cell works if `ipywidgets` is installed in your notebook kernel. If not,
# use the manual viewer above.

# %%
try:
    import ipywidgets as widgets
    from IPython.display import display

    product_widget = widgets.Dropdown(
        options=available_products(prices),
        value="VELVETFRUIT_EXTRACT" if "VELVETFRUIT_EXTRACT" in available_products(prices) else available_products(prices)[0],
        description="Product",
    )
    day_widget = widgets.Dropdown(
        options=[None] + available_days(prices),
        value=available_days(prices)[0],
        description="Day",
    )
    bot_widget = widgets.SelectMultiple(
        options=available_bots(trades),
        value=tuple(bot for bot in ("Mark 67",) if bot in available_bots(trades)),
        description="Bots",
        rows=8,
    )
    background_widget = widgets.Checkbox(
        value=True,
        description="Background trades",
    )

    def _interactive_plot(product, day, bots, background):
        return plot_product_trades(
            prices,
            trades,
            product=product,
            day=day,
            bots=list(bots),
            include_background_trades=background,
        )

    display(
        widgets.VBox(
            [
                widgets.HBox([product_widget, day_widget, background_widget]),
                bot_widget,
            ]
        )
    )
    widgets.interact_output(
        _interactive_plot,
        {
            "product": product_widget,
            "day": day_widget,
            "bots": bot_widget,
            "background": background_widget,
        },
    )
except ImportError:
    print("ipywidgets is not installed in this kernel. Use the manual viewer cells above.")
