"""Render Round 4 counterparty metrics as an interactive HTML report.

Run from the repo root after generating the CSV metrics:

    python3 scripts/render_round4_counterparty_report.py
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Iterable

import pandas as pd

PRODUCT_CSV = Path("results/round4_counterparty_product_metrics.csv")
PAIR_CSV = Path("results/round4_counterparty_pair_metrics.csv")
OUTPUT_HTML = Path("results/round4_counterparty_analysis.html")


PRODUCT_WINDOW_COLUMNS = [
    "bot",
    "product",
    "trades",
    "volume",
    "buy_volume",
    "sell_volume",
    "eod_pnl",
    "same_tick_edge",
    "signed_edge_per_unit",
    "window_pnl_100",
    "window_pnl_500",
    "window_pnl_1000",
    "window_pnl_5000",
    "window_pnl_10000",
    "window_pnl_per_unit_1000",
    "window_pnl_hit_rate_1000",
]

PRODUCT_DIRECTION_COLUMNS = [
    "bot",
    "product",
    "volume",
    "avg_trade_price",
    "avg_mid_at_trade",
    "avg_trade_minus_mid",
    "signed_edge_per_unit",
    "past_move_1000",
    "future_move_100",
    "hit_rate_100",
    "future_move_500",
    "hit_rate_500",
    "future_move_1000",
    "hit_rate_1000",
    "future_move_5000",
    "hit_rate_5000",
    "future_move_10000",
    "hit_rate_10000",
]

PAIR_WINDOW_COLUMNS = [
    "bot",
    "product",
    "side",
    "counterparty",
    "trades",
    "volume",
    "eod_pnl",
    "same_tick_edge",
    "signed_edge_per_unit",
    "window_pnl_1000",
    "window_pnl_per_unit_1000",
    "window_pnl_hit_rate_1000",
    "future_move_1000",
    "hit_rate_1000",
    "window_pnl_10000",
    "window_pnl_per_unit_10000",
    "window_pnl_hit_rate_10000",
    "future_move_10000",
    "hit_rate_10000",
]

LABELS = {
    "bot": "Bot",
    "product": "Product",
    "side": "Side",
    "counterparty": "Counterparty",
    "trades": "Trades",
    "volume": "Vol",
    "buy_volume": "Buy",
    "sell_volume": "Sell",
    "eod_pnl": "EOD PnL",
    "same_tick_edge": "Edge",
    "signed_edge_per_unit": "Exec/mid",
    "avg_trade_price": "TradePx",
    "avg_mid_at_trade": "Mid@Trade",
    "avg_trade_minus_mid": "Px-Mid",
    "past_move_1000": "Past 1k",
    "future_move_100": "F100",
    "future_move_500": "F500",
    "future_move_1000": "F1k",
    "future_move_5000": "F5k",
    "future_move_10000": "F10k",
    "hit_rate_100": "H100%",
    "hit_rate_500": "H500%",
    "hit_rate_1000": "H1k%",
    "hit_rate_5000": "H5k%",
    "hit_rate_10000": "H10k%",
    "window_pnl_100": "P100",
    "window_pnl_500": "P500",
    "window_pnl_1000": "P1k",
    "window_pnl_5000": "P5k",
    "window_pnl_10000": "P10k",
    "window_pnl_per_unit_1000": "P1k/u",
    "window_pnl_per_unit_10000": "P10k/u",
    "window_pnl_hit_rate_1000": "P1k hit%",
    "window_pnl_hit_rate_10000": "P10k hit%",
}


def _format_value(column: str, value: object) -> str:
    if pd.isna(value):
        return ""
    if column in {"bot", "product", "side", "counterparty"}:
        return str(value)
    if column in {"trades", "volume", "buy_volume", "sell_volume"}:
        return f"{int(value):,}"
    if column.startswith("hit_rate_") or column.startswith("window_pnl_hit_rate_"):
        return f"{float(value):.1f}"
    if (
        column.startswith("future_move_")
        or column.startswith("past_move_")
        or column.startswith("window_pnl_per_unit_")
        or column
        in {
            "signed_edge_per_unit",
            "avg_trade_minus_mid",
            "avg_trade_price",
            "avg_mid_at_trade",
        }
    ):
        return f"{float(value):,.3f}"
    return f"{float(value):,.1f}"


def _table_html(
    df: pd.DataFrame,
    columns: list[str],
    table_id: str,
    title: str,
    subtitle: str,
) -> str:
    rows = []
    for _, row in df[columns].iterrows():
        cells = []
        for column in columns:
            raw = row[column]
            text = _format_value(column, raw)
            sort_value = "" if pd.isna(raw) else str(raw)
            cells.append(
                f'<td data-sort="{escape(sort_value)}">{escape(text)}</td>'
            )
        rows.append("<tr>" + "".join(cells) + "</tr>")

    headers = "".join(
        f"<th>{escape(LABELS.get(column, column))}</th>" for column in columns
    )
    body = "\n".join(rows)
    return f"""
<section class="table-card">
  <div class="table-title-row">
    <div>
      <h2>{escape(title)}</h2>
      <p>{escape(subtitle)}</p>
    </div>
    <input class="table-search" type="search" data-table="{table_id}" placeholder="Search this table">
  </div>
  <div class="table-wrap">
    <table id="{table_id}" class="metric-table">
      <thead><tr>{headers}</tr></thead>
      <tbody>
        {body}
      </tbody>
    </table>
  </div>
</section>
"""


def _card(title: str, value: str, subtitle: str) -> str:
    return f"""
<div class="summary-card">
  <div class="summary-title">{escape(title)}</div>
  <div class="summary-value">{escape(value)}</div>
  <div class="summary-subtitle">{escape(subtitle)}</div>
</div>
"""


def _best_row(df: pd.DataFrame, column: str, ascending: bool = False) -> pd.Series:
    return df.sort_values(column, ascending=ascending, kind="stable").iloc[0]


def _summary_cards(product_metrics: pd.DataFrame) -> str:
    substantial = product_metrics[product_metrics["volume"] >= 100].copy()
    best_p1k = _best_row(substantial, "window_pnl_1000")
    worst_p1k = _best_row(substantial, "window_pnl_1000", ascending=True)
    best_f1k = _best_row(substantial, "future_move_1000")
    worst_f1k = _best_row(substantial, "future_move_1000", ascending=True)

    cards = [
        _card(
            "Best P1k",
            f"{best_p1k['bot']} / {best_p1k['product']}",
            f"{best_p1k['window_pnl_1000']:,.1f} total, {best_p1k['window_pnl_per_unit_1000']:.3f} per unit",
        ),
        _card(
            "Worst P1k",
            f"{worst_p1k['bot']} / {worst_p1k['product']}",
            f"{worst_p1k['window_pnl_1000']:,.1f} total, {worst_p1k['window_pnl_per_unit_1000']:.3f} per unit",
        ),
        _card(
            "Best Direction",
            f"{best_f1k['bot']} / {best_f1k['product']}",
            f"F1k {best_f1k['future_move_1000']:.3f}, hit {best_f1k['hit_rate_1000']:.1f}%",
        ),
        _card(
            "Worst Direction",
            f"{worst_f1k['bot']} / {worst_f1k['product']}",
            f"F1k {worst_f1k['future_move_1000']:.3f}, hit {worst_f1k['hit_rate_1000']:.1f}%",
        ),
    ]
    return "\n".join(cards)


def _options(values: Iterable[str]) -> str:
    return "\n".join(f'<option value="{escape(str(value))}">{escape(str(value))}</option>' for value in values)


def render_report(product_metrics: pd.DataFrame, pair_metrics: pd.DataFrame) -> str:
    substantial_products = product_metrics[product_metrics["volume"] >= 100].copy()
    significant_pairs = pair_metrics[pair_metrics["volume"] >= 100].copy()
    bots = sorted(product_metrics["bot"].dropna().unique())
    products = sorted(product_metrics["product"].dropna().unique())

    tables = [
        _table_html(
            substantial_products,
            PRODUCT_WINDOW_COLUMNS,
            "product-window",
            "Product Window PnL",
            "Substantial bot/product rows only, volume >= 100. P* columns mark execution price to future mid.",
        ),
        _table_html(
            substantial_products,
            PRODUCT_DIRECTION_COLUMNS,
            "product-direction",
            "Product Direction And Execution",
            "Mid-to-mid future movement, hit rates, and execution price versus contemporaneous mid.",
        ),
        _table_html(
            significant_pairs,
            PAIR_WINDOW_COLUMNS,
            "pair-window",
            "Significant Counterparty Pairs",
            "Pair rows with volume >= 100.",
        ),
        _table_html(
            product_metrics,
            list(product_metrics.columns),
            "product-raw",
            "Raw Product Metrics",
            "Every product row and every computed column from the product CSV.",
        ),
        _table_html(
            pair_metrics,
            list(pair_metrics.columns),
            "pair-raw",
            "Raw Pair Metrics",
            "Every pair row and every computed column from the pair CSV.",
        ),
    ]

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Round 4 Counterparty Analysis</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #0f172a;
      --panel: #111827;
      --panel-2: #1f2937;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --border: #374151;
      --accent: #93c5fd;
      --positive: #86efac;
      --negative: #fca5a5;
    }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 10;
      padding: 20px 28px;
      background: linear-gradient(180deg, rgba(15, 23, 42, 0.98), rgba(15, 23, 42, 0.92));
      border-bottom: 1px solid var(--border);
      backdrop-filter: blur(10px);
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 24px;
    }}
    h2 {{
      margin: 0 0 4px;
      font-size: 18px;
    }}
    p {{
      margin: 0;
      color: var(--muted);
    }}
    a {{
      color: var(--accent);
    }}
    main {{
      padding: 20px 28px 48px;
    }}
    .controls, .summary-grid {{
      display: grid;
      gap: 12px;
      margin-bottom: 18px;
    }}
    .controls {{
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      align-items: end;
      padding: 14px;
      border: 1px solid var(--border);
      border-radius: 12px;
      background: var(--panel);
    }}
    label {{
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
    }}
    input, select, button {{
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel-2);
      color: var(--text);
      padding: 9px 10px;
      font: inherit;
    }}
    button {{
      cursor: pointer;
    }}
    .summary-grid {{
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    }}
    .summary-card, .table-card {{
      border: 1px solid var(--border);
      border-radius: 12px;
      background: var(--panel);
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.18);
    }}
    .summary-card {{
      padding: 14px;
    }}
    .summary-title {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .summary-value {{
      margin-top: 8px;
      font-size: 18px;
      font-weight: 700;
    }}
    .summary-subtitle {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 13px;
    }}
    .table-card {{
      margin: 18px 0;
      overflow: hidden;
    }}
    .table-title-row {{
      display: flex;
      gap: 12px;
      justify-content: space-between;
      align-items: start;
      padding: 14px;
      border-bottom: 1px solid var(--border);
    }}
    .table-search {{
      min-width: 240px;
    }}
    .table-wrap {{
      max-height: 72vh;
      overflow: auto;
    }}
    table {{
      border-collapse: separate;
      border-spacing: 0;
      width: max-content;
      min-width: 100%;
      font-variant-numeric: tabular-nums;
      font-size: 13px;
    }}
    th, td {{
      border-right: 1px solid var(--border);
      border-bottom: 1px solid var(--border);
      padding: 7px 9px;
      white-space: nowrap;
      text-align: right;
    }}
    th:first-child, td:first-child,
    th:nth-child(2), td:nth-child(2) {{
      text-align: left;
    }}
    th {{
      position: sticky;
      top: 0;
      z-index: 2;
      background: #020617;
      color: #cbd5e1;
      cursor: pointer;
      user-select: none;
    }}
    tbody tr:nth-child(even) {{
      background: rgba(255, 255, 255, 0.025);
    }}
    tbody tr:hover {{
      background: rgba(147, 197, 253, 0.12);
    }}
    .hidden {{
      display: none;
    }}
    .note {{
      margin: 14px 0 18px;
      color: var(--muted);
      max-width: 1100px;
      line-height: 1.5;
    }}
    @media (max-width: 700px) {{
      header, main {{
        padding-left: 14px;
        padding-right: 14px;
      }}
      .table-title-row {{
        display: grid;
      }}
      .table-search {{
        min-width: 0;
        width: 100%;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Round 4 Counterparty Analysis</h1>
    <p>Interactive view of product and pair metrics. Source files:
      <a href="findings_round4_counterparties.md">findings markdown</a>,
      <a href="round4_counterparty_product_metrics.csv">product CSV</a>,
      <a href="round4_counterparty_pair_metrics.csv">pair CSV</a>.
    </p>
  </header>
  <main>
    <section class="controls" aria-label="global filters">
      <label>Global Search
        <input id="global-search" type="search" placeholder="bot, product, counterparty, number">
      </label>
      <label>Bot
        <select id="bot-filter">
          <option value="">All bots</option>
          {_options(bots)}
        </select>
      </label>
      <label>Product
        <select id="product-filter">
          <option value="">All products</option>
          {_options(products)}
        </select>
      </label>
      <label>Min Volume
        <input id="min-volume" type="number" min="0" step="1" placeholder="0">
      </label>
      <button id="reset-filters" type="button">Reset Filters</button>
    </section>

    <section class="summary-grid">
      {_summary_cards(product_metrics)}
    </section>

    <p class="note">
      Definitions: P* is execution-to-future-mid PnL for the given tick window.
      F* is mid-to-mid signed future move in the bot's trade direction.
      Exec/mid is side-adjusted execution quality; positive means buys below mid or sells above mid.
      Click any column header to sort. Use the global filters or per-table search boxes to narrow rows.
    </p>

    {"".join(tables)}
  </main>
  <script>
    function numericValue(text) {{
      const cleaned = text.replace(/,/g, "").replace(/%/g, "").trim();
      if (cleaned === "") return NaN;
      return Number(cleaned);
    }}

    function getCellText(row, index) {{
      const cell = row.cells[index];
      return cell ? cell.textContent.trim() : "";
    }}

    function getColumnIndex(table, names) {{
      const headers = Array.from(table.tHead.rows[0].cells).map((cell) => cell.textContent.trim());
      return headers.findIndex((header) => names.includes(header));
    }}

    function rowMatchesFilters(row, table, localSearch) {{
      const globalSearch = document.getElementById("global-search").value.toLowerCase();
      const botFilter = document.getElementById("bot-filter").value.toLowerCase();
      const productFilter = document.getElementById("product-filter").value.toLowerCase();
      const minVolume = Number(document.getElementById("min-volume").value || 0);
      const text = row.textContent.toLowerCase();
      if (globalSearch && !text.includes(globalSearch)) return false;
      if (localSearch && !text.includes(localSearch)) return false;

      const botIndex = getColumnIndex(table, ["Bot", "bot"]);
      const productIndex = getColumnIndex(table, ["Product", "product"]);
      const volumeIndex = getColumnIndex(table, ["Vol", "volume"]);

      if (botFilter && getCellText(row, botIndex).toLowerCase() !== botFilter) return false;
      if (productFilter && getCellText(row, productIndex).toLowerCase() !== productFilter) return false;
      if (minVolume && numericValue(getCellText(row, volumeIndex)) < minVolume) return false;
      return true;
    }}

    function applyFilters() {{
      document.querySelectorAll("table.metric-table").forEach((table) => {{
        const localInput = document.querySelector(`input[data-table="${{table.id}}"]`);
        const localSearch = localInput ? localInput.value.toLowerCase() : "";
        Array.from(table.tBodies[0].rows).forEach((row) => {{
          row.classList.toggle("hidden", !rowMatchesFilters(row, table, localSearch));
        }});
      }});
    }}

    function sortTable(table, columnIndex) {{
      const tbody = table.tBodies[0];
      const current = table.dataset.sortColumn === String(columnIndex) ? table.dataset.sortDir : "none";
      const direction = current === "asc" ? "desc" : "asc";
      const rows = Array.from(tbody.rows);
      rows.sort((a, b) => {{
        const aText = getCellText(a, columnIndex);
        const bText = getCellText(b, columnIndex);
        const aNum = numericValue(aText);
        const bNum = numericValue(bText);
        let comparison;
        if (!Number.isNaN(aNum) && !Number.isNaN(bNum)) {{
          comparison = aNum - bNum;
        }} else {{
          comparison = aText.localeCompare(bText);
        }}
        return direction === "asc" ? comparison : -comparison;
      }});
      rows.forEach((row) => tbody.appendChild(row));
      table.dataset.sortColumn = String(columnIndex);
      table.dataset.sortDir = direction;
    }}

    document.querySelectorAll("th").forEach((header) => {{
      header.addEventListener("click", () => sortTable(header.closest("table"), header.cellIndex));
    }});
    document.querySelectorAll("input, select").forEach((input) => {{
      input.addEventListener("input", applyFilters);
      input.addEventListener("change", applyFilters);
    }});
    document.getElementById("reset-filters").addEventListener("click", () => {{
      document.getElementById("global-search").value = "";
      document.getElementById("bot-filter").value = "";
      document.getElementById("product-filter").value = "";
      document.getElementById("min-volume").value = "";
      document.querySelectorAll(".table-search").forEach((input) => (input.value = ""));
      applyFilters();
    }});
  </script>
</body>
</html>
"""


def main() -> None:
    product_metrics = pd.read_csv(PRODUCT_CSV)
    pair_metrics = pd.read_csv(PAIR_CSV)
    OUTPUT_HTML.write_text(render_report(product_metrics, pair_metrics))
    print(f"Wrote {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
