"""The order service: what each customer has bought."""

from __future__ import annotations

import itertools
from typing import Any

from shop.bus import Bus
from shop.errors import UnknownUser
from shop.log import log
from shop.store import Store

_ids = itertools.count(1)

_REQUEST = "request:"


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

    def create_order(self, user_id: str, amount_pence: int,
                     request_id: str | None = None) -> str:
        """Record an order and announce it with `order.created`. Returns the order id.

        With a `request_id`, a retry of the same request returns the first
        order's id and creates nothing. The request is reserved before the
        order is written, so a failure between the two writes is finished by
        the retry rather than duplicated. Reusing a request id for a
        different order raises ValueError.

        Raises UnknownUser for a user this service has not heard of, and
        ValueError unless the amount is a positive whole number of pence.
        """
        if user_id not in self.known_users:
            raise UnknownUser(user_id)
        if not isinstance(amount_pence, int) or isinstance(amount_pence, bool) \
                or amount_pence <= 0:
            raise ValueError("amount_pence must be a positive whole number of pence")
        if request_id is None:
            return self._write_order(f"o{next(_ids)}", user_id, amount_pence)
        reservation = self.store.get(_REQUEST + request_id)
        if reservation is None:
            order_id = f"o{next(_ids)}"
            self.store.put(_REQUEST + request_id, {
                "kind": "request", "order_id": order_id,
                "user_id": user_id, "amount_pence": amount_pence})
        else:
            if (reservation["user_id"], reservation["amount_pence"]) != (user_id, amount_pence):
                raise ValueError(f"request id {request_id!r} was used for a different order")
            order_id = reservation["order_id"]
            if self.store.get(order_id) is not None:
                return str(order_id)
        return self._write_order(order_id, user_id, amount_pence)

    def _write_order(self, order_id: str, user_id: str, amount_pence: int) -> str:
        self.store.put(order_id, {"kind": "order", "user_id": user_id,
                                  "amount_pence": amount_pence})
        log("orders", "order.created", order_id=order_id, user_id=user_id)
        self.bus.publish("order.created", {"order_id": order_id, "user_id": user_id,
                                           "amount_pence": amount_pence})
        return order_id

    def orders_for(self, user_id: str) -> list[dict[str, Any]]:
        """Every order the user has made, oldest first."""
        return [{"order_id": k, "user_id": v["user_id"], "amount_pence": v["amount_pence"]}
                for k, v in self.store.items()
                if v.get("kind") == "order" and v["user_id"] == user_id]
