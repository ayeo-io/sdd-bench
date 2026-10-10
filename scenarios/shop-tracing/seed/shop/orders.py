"""The order service: what each customer has bought."""

from __future__ import annotations

import itertools
from typing import Any

from shop.bus import Bus
from shop.errors import UnknownUser
from shop.log import log
from shop.store import Store

_ids = itertools.count(1)


class OrderService:
    """Holds orders. Learns which users exist from `user.created`."""

    def __init__(self, bus: Bus) -> None:
        self.bus = bus
        self.store = Store()
        self.known_users: set[str] = set()
        bus.subscribe("user.created", self._on_user_created)

    def _on_user_created(self, message: dict[str, Any]) -> None:
        user_id = message["payload"]["user_id"]
        self.known_users.add(user_id)
        log("orders", "user.known", user_id=user_id)

    def create_order(self, user_id: str, amount_pence: int) -> str:
        """Record an order and announce it with `order.created`. Returns the order id.

        Raises UnknownUser for a user this service has not heard of, and
        ValueError unless the amount is a positive whole number of pence.
        """
        if user_id not in self.known_users:
            raise UnknownUser(user_id)
        if not isinstance(amount_pence, int) or amount_pence <= 0:
            raise ValueError("amount_pence must be a positive whole number of pence")
        order_id = f"o{next(_ids)}"
        self.store.put(order_id, {"user_id": user_id, "amount_pence": amount_pence})
        log("orders", "order.created", order_id=order_id, user_id=user_id)
        self.bus.publish("order.created", {"order_id": order_id, "user_id": user_id,
                                           "amount_pence": amount_pence})
        return order_id

    def orders_for(self, user_id: str) -> list[dict[str, Any]]:
        """Every order the user has made, oldest first."""
        return [{"order_id": k, **v} for k, v in self.store.items()
                if v["user_id"] == user_id]
