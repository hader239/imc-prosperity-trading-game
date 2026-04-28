from datamodel import Order, OrderDepth, Trade, TradingState
from typing import Any, Dict, List, Optional, Tuple
import json


PRODUCTS = {
    "HYDROGEL_PACK": {
        "position_limit": 200,
        "test_limit": 100,
        "min_edge": 5.0,
        "inventory_skew": 0.08,
        "inside_ticks": 2,
        "clip": 6,
    },
    "VEV_4000": {
        "position_limit": 300,
        "test_limit": 60,
        "min_edge": 7.0,
        "inventory_skew": 0.15,
        "inside_ticks": 2,
        "clip": 3,
    },
}


class Trader:
    """Try to copy Mark 14's role as top-of-book liquidity.

    Historical Round 4 data shows Mark 14 made money by buying at best bid and
    selling at best ask against Mark 38 in HYDROGEL_PACK and VEV_4000. This
    strategy stands one tick inside the public spread, but only when the quote
    still has enough edge versus the current mid. It scales clips up from the
    probe version and raises the required edge as inventory accumulates.
    """

    def run(self, state: TradingState):
        memory = self._load_memory(state.traderData)
        result: Dict[str, List[Order]] = {}

        for product, cfg in PRODUCTS.items():
            depth = state.order_depths.get(product)
            if depth is None:
                continue

            best_bid, best_ask = self._best_quotes(depth)
            if best_bid is None or best_ask is None:
                continue

            mid = (best_bid + best_ask) / 2
            position = state.position.get(product, 0)
            orders: List[Order] = []

            own_fills = self._unseen_own_fills(
                product, state.own_trades.get(product, []), memory
            )
            if own_fills:
                self._log(
                    "fills",
                    state.timestamp,
                    {
                        "product": product,
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

            inside_ticks = int(cfg["inside_ticks"])
            buy_price = best_bid + inside_ticks
            sell_price = best_ask - inside_ticks
            min_edge = float(cfg["min_edge"])
            inventory_skew = float(cfg["inventory_skew"])
            test_limit = int(cfg["test_limit"])
            position_limit = int(cfg["position_limit"])
            clip = int(cfg["clip"])

            buy_capacity = min(test_limit, position_limit) - position
            sell_capacity = min(test_limit, position_limit) + position
            buy_required_edge = min_edge + max(position, 0) * inventory_skew
            sell_required_edge = min_edge + max(-position, 0) * inventory_skew

            if buy_capacity > 0 and buy_price < best_ask:
                buy_edge = mid - buy_price
                if buy_edge >= buy_required_edge:
                    orders.append(Order(product, buy_price, min(clip, buy_capacity)))

            if sell_capacity > 0 and sell_price > best_bid:
                sell_edge = sell_price - mid
                if sell_edge >= sell_required_edge:
                    orders.append(Order(product, sell_price, -min(clip, sell_capacity)))

            if orders:
                self._log(
                    "orders",
                    state.timestamp,
                    {
                        "product": product,
                        "position": position,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "mid": mid,
                        "inside_ticks": inside_ticks,
                        "buy_required_edge": buy_required_edge,
                        "sell_required_edge": sell_required_edge,
                        "orders": [
                            {"price": order.price, "qty": order.quantity}
                            for order in orders
                        ],
                    },
                )
                result[product] = orders

        return result, 0, self._dump_memory(memory)

    def _best_quotes(self, depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        best_bid = max(depth.buy_orders) if depth.buy_orders else None
        best_ask = min(depth.sell_orders) if depth.sell_orders else None
        return best_bid, best_ask

    def _unseen_own_fills(
        self, product: str, trades: List[Trade], memory: Dict[str, Any]
    ) -> List[Trade]:
        key_name = f"seen_own_fills_{product}"
        seen_keys = list(memory.get(key_name, []))
        seen = set(seen_keys)
        unseen: List[Trade] = []

        for trade in trades:
            key = self._trade_key(trade)
            if key in seen:
                continue
            seen.add(key)
            seen_keys.append(key)
            unseen.append(trade)

        memory[key_name] = seen_keys[-100:]
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

    def _load_memory(self, trader_data: str) -> Dict[str, Any]:
        if not trader_data:
            return {}
        try:
            loaded = json.loads(trader_data)
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _dump_memory(self, memory: Dict[str, Any]) -> str:
        return json.dumps(memory, separators=(",", ":"))

    def _log(self, kind: str, timestamp: int, payload: Dict[str, Any]) -> None:
        print("M14_LIQ " + json.dumps({"kind": kind, "ts": timestamp, **payload}))
