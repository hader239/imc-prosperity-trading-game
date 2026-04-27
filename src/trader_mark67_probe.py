from datamodel import Order, OrderDepth, Trade, TradingState
from typing import Any, Dict, List, Optional, Tuple
import json


PRODUCT = "VELVETFRUIT_EXTRACT"
MARK_67 = "Mark 67"

POSITION_LIMIT = 200
MAX_TEST_POSITION = 1

# The historical signal was strongest around 1,000 timestamp units.
HOLD_TICKS = 1000
TAKE_PROFIT_TICKS = 2.0
STOP_LOSS_TICKS = 4.0
EXPECTED_MARK67_EDGE_TICKS = 2.0
MIN_ENTRY_PROFIT_TICKS = 1.0

# Trade exactly one unit per test so the official backtester gives us a clear
# yes/no answer for whether the visible signal is exploitable.
TEST_QTY = 1


class Trader:
    def run(self, state: TradingState):
        memory = self._load_memory(state.traderData)
        result: Dict[str, List[Order]] = {}
        orders: List[Order] = []

        depth = state.order_depths.get(PRODUCT)
        if depth is None:
            return result, 0, self._dump_memory(memory)

        best_bid, bid_volume, best_ask, ask_volume = self._best_quotes(depth)
        if best_bid is None or best_ask is None:
            return result, 0, self._dump_memory(memory)

        mid = (best_bid + best_ask) / 2
        position = state.position.get(PRODUCT, 0)

        own_fills = self._unseen_own_fills(state.own_trades.get(PRODUCT, []), memory)
        if own_fills:
            self._log(
                "fills",
                state.timestamp,
                {
                    "position": position,
                    "fills": [
                        {
                            "timestamp": trade.timestamp,
                            "price": trade.price,
                            "qty": trade.quantity,
                            "buyer": trade.buyer,
                            "seller": trade.seller,
                        }
                        for trade in own_fills
                    ],
                },
            )

        mark67_trades = self._unseen_mark67_buys(
            state.market_trades.get(PRODUCT, []), memory
        )
        if mark67_trades:
            total_qty = sum(trade.quantity for trade in mark67_trades)
            sellers = self._seller_counts(mark67_trades)
            mark67_vwap = self._vwap(mark67_trades)
            max_entry_price = int(
                mark67_vwap + EXPECTED_MARK67_EDGE_TICKS - MIN_ENTRY_PROFIT_TICKS
            )
            memory["last_signal_ts"] = state.timestamp
            memory["last_signal_mid"] = mid
            memory["signal_count"] = int(memory.get("signal_count", 0)) + len(
                mark67_trades
            )

            self._log(
                "signal",
                state.timestamp,
                {
                    "mark67_qty": total_qty,
                    "sellers": sellers,
                    "mid": mid,
                    "position": position,
                    "mark67_vwap": mark67_vwap,
                    "max_entry_price": max_entry_price,
                    "market_trades": [
                        {
                            "timestamp": trade.timestamp,
                            "price": trade.price,
                            "qty": trade.quantity,
                            "seller": trade.seller,
                        }
                        for trade in mark67_trades
                    ],
                },
            )

            buy_capacity = min(MAX_TEST_POSITION, POSITION_LIMIT) - max(position, 0)
            if buy_capacity > 0:
                buy_qty = min(TEST_QTY, buy_capacity)
                if best_ask <= max_entry_price:
                    orders.append(Order(PRODUCT, best_ask, min(buy_qty, ask_volume)))
                elif best_bid < max_entry_price:
                    passive_price = min(best_bid + 1, max_entry_price)
                    if passive_price < best_ask:
                        orders.append(Order(PRODUCT, passive_price, buy_qty))

        elif position > 0:
            exit_reason = self._exit_reason(state.timestamp, mid, memory)
            if exit_reason is not None:
                sell_qty = min(position, bid_volume, TEST_QTY)
                if sell_qty > 0:
                    orders.append(Order(PRODUCT, best_bid, -sell_qty))
                    self._log(
                        "exit",
                        state.timestamp,
                        {
                            "reason": exit_reason,
                            "mid": mid,
                            "position": position,
                            "sell_qty": sell_qty,
                            "last_signal_ts": memory.get("last_signal_ts"),
                            "last_signal_mid": memory.get("last_signal_mid"),
                        },
                    )

        elif position < 0:
            # This probe should never intentionally go short. If it happens,
            # flatten immediately so the Mark 67 test remains interpretable.
            buy_qty = min(-position, ask_volume, TEST_QTY)
            if buy_qty > 0:
                orders.append(Order(PRODUCT, best_ask, buy_qty))
                self._log(
                    "flatten_short",
                    state.timestamp,
                    {"position": position, "buy_qty": buy_qty, "mid": mid},
                )

        if orders:
            self._log(
                "orders",
                state.timestamp,
                {
                    "position": position,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "orders": [
                        {"price": order.price, "qty": order.quantity}
                        for order in orders
                    ],
                },
            )

        result[PRODUCT] = orders
        return result, 0, self._dump_memory(memory)

    def _unseen_mark67_buys(
        self, trades: List[Trade], memory: Dict[str, Any]
    ) -> List[Trade]:
        seen_keys = list(memory.get("seen_mark67", []))
        seen = set(seen_keys)
        unseen: List[Trade] = []
        for trade in trades:
            if trade.buyer != MARK_67:
                continue
            key = self._trade_key(trade)
            if key in seen:
                continue
            seen.add(key)
            seen_keys.append(key)
            unseen.append(trade)

        memory["seen_mark67"] = seen_keys[-50:]
        return unseen

    def _unseen_own_fills(
        self, trades: List[Trade], memory: Dict[str, Any]
    ) -> List[Trade]:
        seen_keys = list(memory.get("seen_own_fills", []))
        seen = set(seen_keys)
        unseen: List[Trade] = []
        for trade in trades:
            key = self._trade_key(trade)
            if key in seen:
                continue
            seen.add(key)
            seen_keys.append(key)
            unseen.append(trade)

        memory["seen_own_fills"] = seen_keys[-100:]
        return unseen

    def _trade_key(self, trade: Trade) -> str:
        return "|".join(
            [
                str(trade.timestamp),
                str(trade.buyer),
                str(trade.seller),
                str(trade.price),
                str(trade.quantity),
            ]
        )

    def _seller_counts(self, trades: List[Trade]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for trade in trades:
            seller = trade.seller or "UNKNOWN"
            counts[seller] = counts.get(seller, 0) + trade.quantity
        return counts

    def _vwap(self, trades: List[Trade]) -> float:
        quantity = sum(trade.quantity for trade in trades)
        if quantity == 0:
            return 0.0
        notional = sum(trade.price * trade.quantity for trade in trades)
        return notional / quantity

    def _best_quotes(
        self, depth: OrderDepth
    ) -> Tuple[Optional[int], int, Optional[int], int]:
        best_bid = max(depth.buy_orders) if depth.buy_orders else None
        best_ask = min(depth.sell_orders) if depth.sell_orders else None
        bid_volume = depth.buy_orders[best_bid] if best_bid is not None else 0
        ask_volume = -depth.sell_orders[best_ask] if best_ask is not None else 0
        return best_bid, bid_volume, best_ask, ask_volume

    def _exit_reason(
        self, timestamp: int, mid: float, memory: Dict[str, Any]
    ) -> Optional[str]:
        last_signal_ts = memory.get("last_signal_ts")
        last_signal_mid = memory.get("last_signal_mid")
        if last_signal_ts is None or last_signal_mid is None:
            return "no_signal_memory"

        age = timestamp - int(last_signal_ts)
        signal_mid = float(last_signal_mid)
        if mid >= signal_mid + TAKE_PROFIT_TICKS:
            return "take_profit"
        if age >= HOLD_TICKS:
            return "timeout"
        if mid <= signal_mid - STOP_LOSS_TICKS:
            return "stop_loss"
        return None

    def _load_memory(self, trader_data: str) -> Dict[str, Any]:
        if not trader_data:
            return self._empty_memory()
        try:
            loaded = json.loads(trader_data)
        except Exception:
            return self._empty_memory()
        if not isinstance(loaded, dict):
            return self._empty_memory()
        loaded.setdefault("last_signal_ts", None)
        loaded.setdefault("last_signal_mid", None)
        loaded.setdefault("signal_count", 0)
        loaded.setdefault("seen_mark67", [])
        loaded.setdefault("seen_own_fills", [])
        return loaded

    def _empty_memory(self) -> Dict[str, Any]:
        return {
            "last_signal_ts": None,
            "last_signal_mid": None,
            "signal_count": 0,
            "seen_mark67": [],
            "seen_own_fills": [],
        }

    def _dump_memory(self, memory: Dict[str, Any]) -> str:
        return json.dumps(memory, separators=(",", ":"))

    def _log(self, kind: str, timestamp: int, payload: Dict[str, Any]) -> None:
        print("M67_PROBE " + json.dumps({"kind": kind, "ts": timestamp, **payload}))
