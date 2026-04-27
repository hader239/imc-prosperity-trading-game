"""Load Prosperity datasets and run logs into pandas DataFrames.

Two distinct artifact types — both use `;` as the delimiter:

1. **Data Capsule CSVs** (in `data/round-N/`) — historical price/trade
   bundles IMC ships before each round. Schema:

   prices_round_<N>_day_<D>.csv:
     day; timestamp; product;
     bid_price_1; bid_volume_1; bid_price_2; bid_volume_2; bid_price_3; bid_volume_3;
     ask_price_1; ask_volume_1; ask_price_2; ask_volume_2; ask_price_3; ask_volume_3;
     mid_price; profit_and_loss

   trades_round_<N>_day_<D>.csv:
     timestamp; buyer; seller; symbol; currency; price; quantity

2. **Submission run logs** (in `logs/round-N/`) — the JSON file Prosperity
   hands back after a round runs your `Trader`. Embeds the same price
   schema in the `activitiesLog` field plus a `tradeHistory` array.
"""

from __future__ import annotations

import json
from glob import glob
from io import StringIO
from pathlib import Path
from typing import Iterable, List, Union

import pandas as pd

PathLike = Union[str, Path]


# --- Data Capsule CSVs -----------------------------------------------------


def load_prices_csv(path: PathLike) -> pd.DataFrame:
    """Read one prices_round_*_day_*.csv into a DataFrame."""
    return pd.read_csv(path, sep=";")


def load_trades_csv(path: PathLike) -> pd.DataFrame:
    """Read one trades_round_*_day_*.csv into a DataFrame."""
    return pd.read_csv(path, sep=";")


def load_prices(round_dir: PathLike, days: Iterable[int] | None = None) -> pd.DataFrame:
    """Load and concatenate every prices_*.csv in a round dir.

    `days` filters by the day suffix in the filename (`day_-1`, `day_0`, …).
    Returns a DataFrame sorted by (day, timestamp), with the source
    filename in `_source`.
    """
    return _load_concat(round_dir, "prices_*.csv", days)


def load_trades(round_dir: PathLike, days: Iterable[int] | None = None) -> pd.DataFrame:
    """Load and concatenate every trades_*.csv in a round dir."""
    return _load_concat(round_dir, "trades_*.csv", days)


def _load_concat(
    round_dir: PathLike, pattern: str, days: Iterable[int] | None
) -> pd.DataFrame:
    paths = sorted(glob(str(Path(round_dir) / pattern)))
    if not paths:
        raise FileNotFoundError(f"no files matching {pattern} in {round_dir}")
    if days is not None:
        wanted = {f"day_{d}" for d in days}
        paths = [p for p in paths if any(w in Path(p).name for w in wanted)]
        if not paths:
            raise FileNotFoundError(
                f"no {pattern} matched days={list(days)} in {round_dir}"
            )
    frames: List[pd.DataFrame] = []
    for p in paths:
        df = pd.read_csv(p, sep=";")
        df["_source"] = Path(p).name
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    sort_keys = [c for c in ("day", "timestamp") if c in out.columns]
    if sort_keys:
        out = out.sort_values(sort_keys, kind="stable").reset_index(drop=True)
    return out


# --- Submission run logs ---------------------------------------------------


def load_log_activities(path: PathLike) -> pd.DataFrame:
    """Extract the per-tick price/volume frame from a Prosperity run log."""
    with open(path) as f:
        data = json.load(f)
    return pd.read_csv(StringIO(data["activitiesLog"]), sep=";")


def load_log_trades(path: PathLike) -> pd.DataFrame:
    """Extract the trade history from a Prosperity run log.

    Includes both bot-vs-bot trades and SUBMISSION trades. Filter on
    `buyer == 'SUBMISSION'` or `seller == 'SUBMISSION'` for our fills.
    """
    with open(path) as f:
        data = json.load(f)
    return pd.DataFrame(data["tradeHistory"])
