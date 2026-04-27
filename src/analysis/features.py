"""Fair-value estimators used across the existing traders.

Both functions take a prices DataFrame in the standard 3-level schema
(`bid_price_{1,2,3}`, `bid_volume_{1,2,3}`, `ask_price_{1,2,3}`,
`ask_volume_{1,2,3}`) and return a Series of floats aligned to the
input index.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def wall_mid(df: pd.DataFrame) -> pd.Series:
    """Midpoint of the largest-volume bid level and largest-volume ask level.

    A common fair-value anchor: the price levels with the most resting
    size carry more conviction than the raw best bid/ask. Falls back to
    `mid_price` (standard best-bid/best-ask midpoint) on rows where any
    wall level is missing.
    """
    bid_p = df[[f"bid_price_{i}" for i in (1, 2, 3)]].to_numpy(dtype=float)
    bid_v = df[[f"bid_volume_{i}" for i in (1, 2, 3)]].to_numpy(dtype=float)
    ask_p = df[[f"ask_price_{i}" for i in (1, 2, 3)]].to_numpy(dtype=float)
    ask_v = df[[f"ask_volume_{i}" for i in (1, 2, 3)]].to_numpy(dtype=float)

    bid_v = np.where(np.isnan(bid_p), -np.inf, bid_v)
    ask_v = np.where(np.isnan(ask_p), -np.inf, ask_v)

    bid_wall = np.take_along_axis(bid_p, bid_v.argmax(axis=1)[:, None], axis=1).ravel()
    ask_wall = np.take_along_axis(ask_p, ask_v.argmax(axis=1)[:, None], axis=1).ravel()

    out = (bid_wall + ask_wall) / 2.0
    fallback = df["mid_price"].astype(float).to_numpy() if "mid_price" in df else None
    if fallback is not None:
        bad = np.isnan(out)
        out[bad] = fallback[bad]
    return pd.Series(out, index=df.index, name="wall_mid")


def microprice(df: pd.DataFrame) -> pd.Series:
    """Size-weighted mid: (best_bid*ask_vol + best_ask*bid_vol) / (bid_vol+ask_vol).

    Reacts faster than mid_price on imbalanced books. Falls back to
    mid_price when either touch is missing or both volumes are zero.
    """
    bid_p = df["bid_price_1"].astype(float)
    bid_v = df["bid_volume_1"].astype(float)
    ask_p = df["ask_price_1"].astype(float)
    ask_v = df["ask_volume_1"].astype(float)

    denom = bid_v + ask_v
    out = (bid_p * ask_v + ask_p * bid_v) / denom

    if "mid_price" in df:
        out = out.where(denom > 0, df["mid_price"].astype(float))
    return out.rename("microprice")
