"""Analyze Round 4 named counterparty behavior by bot and product.

The output is meant to back `results/findings_round4_counterparties.md`.
Run from the repo root:

    python3 scripts/analyze_round4_counterparties.py \
        --markdown results/round4_counterparty_product_metrics.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis import load_prices, load_trades

HORIZONS = (100, 500, 1_000, 5_000, 10_000)


def _day_from_source(value: object) -> int | None:
    match = re.search(r"day_(-?\d+)", str(value))
    return int(match.group(1)) if match else None


def _weighted_average(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna()
    if not valid.any():
        return float("nan")
    weights = weights[valid].astype(float)
    denom = weights.sum()
    if denom == 0:
        return float("nan")
    return float((values[valid].astype(float) * weights).sum() / denom)


def _weighted_hit_rate(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna()
    if not valid.any():
        return float("nan")
    weights = weights[valid].astype(float)
    denom = weights.sum()
    if denom == 0:
        return float("nan")
    return float(weights[valid & (values > 0)].sum() / denom * 100.0)


def _markdown_table(rows: Iterable[dict[str, object]], columns: list[str]) -> str:
    rows = list(rows)
    widths = {
        col: max(len(col), *(len(str(row.get(col, ""))) for row in rows))
        for col in columns
    }
    header = "| " + " | ".join(col.ljust(widths[col]) for col in columns) + " |"
    divider = "| " + " | ".join("-" * widths[col] for col in columns) + " |"
    body = [
        "| " + " | ".join(str(row.get(col, "")).ljust(widths[col]) for col in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def _format_number(value: object, decimals: int = 1) -> str:
    if pd.isna(value):
        return ""
    value = float(value)
    if decimals == 0:
        return f"{value:,.0f}"
    return f"{value:,.{decimals}f}"


def normalize_inputs(round_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    prices = load_prices(round_dir).copy()
    trades = load_trades(round_dir).copy()

    if "day" not in trades.columns:
        trades["day"] = trades["_source"].map(_day_from_source)

    prices["day"] = prices["day"].astype(int)
    prices["timestamp"] = prices["timestamp"].astype(int)
    prices["product"] = prices["product"].astype(str)
    prices["mid_price"] = prices["mid_price"].astype(float)

    trades["day"] = trades["day"].astype(int)
    trades["timestamp"] = trades["timestamp"].astype(int)
    trades["symbol"] = trades["symbol"].astype(str)
    trades["buyer"] = trades["buyer"].astype(str)
    trades["seller"] = trades["seller"].astype(str)
    trades["price"] = trades["price"].astype(float)
    trades["quantity"] = trades["quantity"].astype(int)

    return prices, trades


def build_participant_trades(prices: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    current = prices[["day", "timestamp", "product", "mid_price"]].rename(
        columns={"product": "symbol", "mid_price": "current_mid"}
    )
    base = trades.merge(current, on=["day", "timestamp", "symbol"], how="left")

    eod = (
        prices.sort_values(["day", "product", "timestamp"], kind="stable")
        .groupby(["day", "product"], as_index=False)
        .tail(1)[["day", "product", "mid_price"]]
        .rename(columns={"product": "symbol", "mid_price": "eod_mid"})
    )
    start = (
        prices.sort_values(["day", "product", "timestamp"], kind="stable")
        .groupby(["day", "product"], as_index=False)
        .head(1)[["day", "product", "mid_price"]]
        .rename(columns={"product": "symbol", "mid_price": "start_mid"})
    )
    base = base.merge(eod, on=["day", "symbol"], how="left")
    base = base.merge(start, on=["day", "symbol"], how="left")

    for horizon in HORIZONS:
        future = prices[["day", "timestamp", "product", "mid_price"]].copy()
        future["timestamp"] -= horizon
        future = future.rename(
            columns={"product": "symbol", "mid_price": f"future_mid_{horizon}"}
        )
        base = base.merge(future, on=["day", "timestamp", "symbol"], how="left")
        base[f"future_mid_{horizon}"] = base[f"future_mid_{horizon}"].fillna(
            base["eod_mid"]
        )

        past = prices[["day", "timestamp", "product", "mid_price"]].copy()
        past["timestamp"] += horizon
        past = past.rename(
            columns={"product": "symbol", "mid_price": f"past_mid_{horizon}"}
        )
        base = base.merge(past, on=["day", "timestamp", "symbol"], how="left")
        base[f"past_mid_{horizon}"] = base[f"past_mid_{horizon}"].fillna(
            base["start_mid"]
        )

    participant_frames = []
    for side, sign, bot_col, counterparty_col in (
        ("BUY", 1, "buyer", "seller"),
        ("SELL", -1, "seller", "buyer"),
    ):
        frame = base.copy()
        frame["bot"] = frame[bot_col]
        frame["side"] = side
        frame["counterparty"] = frame[counterparty_col]
        frame["side_sign"] = sign
        frame["same_tick_edge"] = (
            sign * (frame["current_mid"] - frame["price"]) * frame["quantity"]
        )
        frame["signed_edge_per_unit"] = sign * (frame["current_mid"] - frame["price"])
        frame["trade_minus_mid"] = frame["price"] - frame["current_mid"]
        frame["eod_pnl"] = (
            sign * (frame["eod_mid"] - frame["price"]) * frame["quantity"]
        )
        for horizon in HORIZONS:
            frame[f"future_move_{horizon}"] = sign * (
                frame[f"future_mid_{horizon}"] - frame["current_mid"]
            )
            frame[f"window_pnl_{horizon}"] = (
                sign
                * (frame[f"future_mid_{horizon}"] - frame["price"])
                * frame["quantity"]
            )
            frame[f"window_pnl_per_unit_{horizon}"] = sign * (
                frame[f"future_mid_{horizon}"] - frame["price"]
            )
            frame[f"past_move_{horizon}"] = sign * (
                frame["current_mid"] - frame[f"past_mid_{horizon}"]
            )
        participant_frames.append(frame)

    return pd.concat(participant_frames, ignore_index=True)


def summarize_products(participant_trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (bot, product), group in participant_trades.groupby(["bot", "symbol"], sort=True):
        row: dict[str, object] = {
            "bot": bot,
            "product": product,
            "trades": len(group),
            "volume": int(group["quantity"].sum()),
            "buy_volume": int(group.loc[group["side"] == "BUY", "quantity"].sum()),
            "sell_volume": int(group.loc[group["side"] == "SELL", "quantity"].sum()),
            "eod_pnl": float(group["eod_pnl"].sum()),
            "same_tick_edge": float(group["same_tick_edge"].sum()),
            "avg_trade_price": _weighted_average(group["price"], group["quantity"]),
            "avg_mid_at_trade": _weighted_average(group["current_mid"], group["quantity"]),
            "avg_trade_minus_mid": _weighted_average(
                group["trade_minus_mid"], group["quantity"]
            ),
            "signed_edge_per_unit": _weighted_average(
                group["signed_edge_per_unit"], group["quantity"]
            ),
            "past_move_1000": _weighted_average(group["past_move_1000"], group["quantity"]),
        }
        for horizon in HORIZONS:
            row[f"future_move_{horizon}"] = _weighted_average(
                group[f"future_move_{horizon}"], group["quantity"]
            )
            row[f"hit_rate_{horizon}"] = _weighted_hit_rate(
                group[f"future_move_{horizon}"], group["quantity"]
            )
            row[f"window_pnl_{horizon}"] = float(group[f"window_pnl_{horizon}"].sum())
            row[f"window_pnl_per_unit_{horizon}"] = _weighted_average(
                group[f"window_pnl_per_unit_{horizon}"], group["quantity"]
            )
            row[f"window_pnl_hit_rate_{horizon}"] = _weighted_hit_rate(
                group[f"window_pnl_per_unit_{horizon}"], group["quantity"]
            )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["bot", "product"], kind="stable")


def summarize_pairs(participant_trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group_cols = ["bot", "product", "side", "counterparty"]
    data = participant_trades.rename(columns={"symbol": "product"})
    for keys, group in data.groupby(group_cols, sort=True):
        bot, product, side, counterparty = keys
        row: dict[str, object] = {
            "bot": bot,
            "product": product,
            "side": side,
            "counterparty": counterparty,
            "trades": len(group),
            "volume": int(group["quantity"].sum()),
            "eod_pnl": float(group["eod_pnl"].sum()),
            "same_tick_edge": float(group["same_tick_edge"].sum()),
            "avg_trade_price": _weighted_average(group["price"], group["quantity"]),
            "avg_mid_at_trade": _weighted_average(group["current_mid"], group["quantity"]),
            "avg_trade_minus_mid": _weighted_average(
                group["trade_minus_mid"], group["quantity"]
            ),
            "signed_edge_per_unit": _weighted_average(
                group["signed_edge_per_unit"], group["quantity"]
            ),
        }
        for horizon in (1_000, 10_000):
            row[f"future_move_{horizon}"] = _weighted_average(
                group[f"future_move_{horizon}"], group["quantity"]
            )
            row[f"hit_rate_{horizon}"] = _weighted_hit_rate(
                group[f"future_move_{horizon}"], group["quantity"]
            )
            row[f"window_pnl_{horizon}"] = float(group[f"window_pnl_{horizon}"].sum())
            row[f"window_pnl_per_unit_{horizon}"] = _weighted_average(
                group[f"window_pnl_per_unit_{horizon}"], group["quantity"]
            )
            row[f"window_pnl_hit_rate_{horizon}"] = _weighted_hit_rate(
                group[f"window_pnl_per_unit_{horizon}"], group["quantity"]
            )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["bot", "product", "volume"], ascending=[True, True, False], kind="stable"
    )


def render_markdown(product_metrics: pd.DataFrame, pair_metrics: pd.DataFrame) -> str:
    product_rows = []
    for _, row in product_metrics.iterrows():
        product_rows.append(
            {
                "Bot": row["bot"],
                "Product": row["product"],
                "Trades": f"{int(row['trades']):,}",
                "Vol": f"{int(row['volume']):,}",
                "Buy": f"{int(row['buy_volume']):,}",
                "Sell": f"{int(row['sell_volume']):,}",
                "EOD PnL": _format_number(row["eod_pnl"], 1),
                "Edge": _format_number(row["same_tick_edge"], 1),
                "TradePx": _format_number(row["avg_trade_price"], 2),
                "Mid@Trade": _format_number(row["avg_mid_at_trade"], 2),
                "Px-Mid": _format_number(row["avg_trade_minus_mid"], 3),
                "Exec/mid": _format_number(row["signed_edge_per_unit"], 3),
                "Past 1k": _format_number(row["past_move_1000"], 3),
                "F100": _format_number(row["future_move_100"], 3),
                "H100%": _format_number(row["hit_rate_100"], 1),
                "P100": _format_number(row["window_pnl_100"], 1),
                "P100/u": _format_number(row["window_pnl_per_unit_100"], 3),
                "F500": _format_number(row["future_move_500"], 3),
                "H500%": _format_number(row["hit_rate_500"], 1),
                "P500": _format_number(row["window_pnl_500"], 1),
                "P500/u": _format_number(row["window_pnl_per_unit_500"], 3),
                "F1k": _format_number(row["future_move_1000"], 3),
                "H1k%": _format_number(row["hit_rate_1000"], 1),
                "P1k": _format_number(row["window_pnl_1000"], 1),
                "P1k/u": _format_number(row["window_pnl_per_unit_1000"], 3),
                "F5k": _format_number(row["future_move_5000"], 3),
                "H5k%": _format_number(row["hit_rate_5000"], 1),
                "P5k": _format_number(row["window_pnl_5000"], 1),
                "P5k/u": _format_number(row["window_pnl_per_unit_5000"], 3),
                "F10k": _format_number(row["future_move_10000"], 3),
                "H10k%": _format_number(row["hit_rate_10000"], 1),
                "P10k": _format_number(row["window_pnl_10000"], 1),
                "P10k/u": _format_number(row["window_pnl_per_unit_10000"], 3),
            }
        )

    pair_rows = []
    significant_pairs = pair_metrics[pair_metrics["volume"] >= 100].copy()
    for _, row in significant_pairs.iterrows():
        pair_rows.append(
            {
                "Bot": row["bot"],
                "Product": row["product"],
                "Side": row["side"],
                "Counterparty": row["counterparty"],
                "Trades": f"{int(row['trades']):,}",
                "Vol": f"{int(row['volume']):,}",
                "EOD PnL": _format_number(row["eod_pnl"], 1),
                "Edge": _format_number(row["same_tick_edge"], 1),
                "TradePx": _format_number(row["avg_trade_price"], 2),
                "Mid@Trade": _format_number(row["avg_mid_at_trade"], 2),
                "Px-Mid": _format_number(row["avg_trade_minus_mid"], 3),
                "Exec/mid": _format_number(row["signed_edge_per_unit"], 3),
                "F1k": _format_number(row["future_move_1000"], 3),
                "H1k%": _format_number(row["hit_rate_1000"], 1),
                "P1k": _format_number(row["window_pnl_1000"], 1),
                "P1k/u": _format_number(row["window_pnl_per_unit_1000"], 3),
                "F10k": _format_number(row["future_move_10000"], 3),
                "H10k%": _format_number(row["hit_rate_10000"], 1),
                "P10k": _format_number(row["window_pnl_10000"], 1),
                "P10k/u": _format_number(row["window_pnl_per_unit_10000"], 3),
            }
        )

    product_columns = [
        "Bot",
        "Product",
        "Trades",
        "Vol",
        "Buy",
        "Sell",
        "EOD PnL",
        "Edge",
        "TradePx",
        "Mid@Trade",
        "Px-Mid",
        "Exec/mid",
        "Past 1k",
        "F100",
        "H100%",
        "P100",
        "P100/u",
        "F500",
        "H500%",
        "P500",
        "P500/u",
        "F1k",
        "H1k%",
        "P1k",
        "P1k/u",
        "F5k",
        "H5k%",
        "P5k",
        "P5k/u",
        "F10k",
        "H10k%",
        "P10k",
        "P10k/u",
    ]
    pair_columns = [
        "Bot",
        "Product",
        "Side",
        "Counterparty",
        "Trades",
        "Vol",
        "EOD PnL",
        "Edge",
        "TradePx",
        "Mid@Trade",
        "Px-Mid",
        "Exec/mid",
        "F1k",
        "H1k%",
        "P1k",
        "P1k/u",
        "F10k",
        "H10k%",
        "P10k",
        "P10k/u",
    ]

    return "\n\n".join(
        [
            "# Round 4 Counterparty Product Metrics",
            "Generated by `python3 scripts/analyze_round4_counterparties.py --markdown results/round4_counterparty_product_metrics.md`.",
            "Metrics are from each named bot's perspective. `EOD PnL` marks trades to the product's same-day closing mid. `Edge` marks trades to the same-tick mid. `TradePx`, `Mid@Trade`, and `Px-Mid` compare execution price to contemporaneous mid without side adjustment. `Exec/mid` is side-adjusted per-unit execution quality: positive means buys below mid or sells above mid. `F*` columns are volume-weighted signed future mid moves; positive means the market moved in the bot's trade direction. `H*%` is the volume-weighted hit rate. `P*` columns are total execution-to-future-mid PnL for that horizon: buys use `(future_mid - trade_price) * quantity`; sells use `(trade_price - future_mid) * quantity`. `P*/u` is the same window PnL per unit. `Past 1k` is the signed move over the previous 1,000 ticks, clipped to the first tick of the day; future horizons are clipped to the last tick of the day.",
            "## Product-Level Metrics",
            _markdown_table(product_rows, product_columns),
            "## Significant Counterparty Pairs",
            "Rows with volume below 100 are omitted here; the CSV includes every pair.",
            _markdown_table(pair_rows, pair_columns),
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round-dir", type=Path, default=Path("data/round-4"))
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--product-csv", type=Path)
    parser.add_argument("--pair-csv", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prices, trades = normalize_inputs(args.round_dir)
    participant_trades = build_participant_trades(prices, trades)
    product_metrics = summarize_products(participant_trades)
    pair_metrics = summarize_pairs(participant_trades)

    if args.product_csv:
        args.product_csv.parent.mkdir(parents=True, exist_ok=True)
        product_metrics.to_csv(args.product_csv, index=False)
    if args.pair_csv:
        args.pair_csv.parent.mkdir(parents=True, exist_ok=True)
        pair_metrics.to_csv(args.pair_csv, index=False)

    markdown = render_markdown(product_metrics, pair_metrics)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown)
    else:
        print(markdown)


if __name__ == "__main__":
    main()
