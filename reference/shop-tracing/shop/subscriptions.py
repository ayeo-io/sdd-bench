"""The subscription service: which mailing lists each customer is on.
Every new customer joins the "news" list."""

from __future__ import annotations

from typing import Any

from shop.bus import Bus
from shop.errors import UnknownUser
from shop.log import log
from shop.store import Store


class SubscriptionService:
    def __init__(self, bus: Bus) -> None:
        self.bus = bus
        self.store = Store()
        self.known_users: set[str] = set()
        bus.subscribe("user.created", self._on_user_created)

    def _on_user_created(self, message: dict[str, Any]) -> None:
        user_id = message["payload"]["user_id"]
        self.known_users.add(user_id)
        self.subscribe(user_id, "news", trace_id=message["headers"].get("trace_id"))

    def subscribe(self, user_id: str, list_name: str,
                  trace_id: str | None = None) -> None:
        if user_id not in self.known_users:
            raise UnknownUser(user_id)
        self.store.put(f"{user_id}:{list_name}", {"user_id": user_id, "list": list_name})
        log("subscriptions", "subscription.created", user_id=user_id, list=list_name,
            trace_id=trace_id)
        self.bus.publish("subscription.created", {"user_id": user_id, "list": list_name},
                         {"trace_id": trace_id})

    def lists_for(self, user_id: str) -> list[str]:
        return [v["list"] for _, v in self.store.items() if v["user_id"] == user_id]
