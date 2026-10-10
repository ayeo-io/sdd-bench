"""An in-memory event bus.

Services publish messages to a topic and subscribe handlers to topics.
Nothing is delivered until `run_pending()` is called, so the order of
events is always explicit.

Delivery is at least once:
- if a handler raises, that message stays pending for that handler and is
  delivered again on the next `run_pending()`; other handlers are not
  affected;
- a message can arrive more than once. `deliver_again()` puts every
  message already delivered back in the queue, which is how a test
  simulates a duplicate.

A message is a dict: {"topic": str, "payload": dict, "headers": dict}.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Handler = Callable[[dict[str, Any]], None]


class Bus:
    """Topics, their handlers, and the messages waiting to be delivered."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}
        self._pending: list[tuple[dict[str, Any], Handler]] = []
        self._delivered: list[tuple[dict[str, Any], Handler]] = []
        self.published: list[dict[str, Any]] = []

    def subscribe(self, topic: str, handler: Handler) -> None:
        """Deliver every later message on `topic` to `handler`."""
        self._handlers.setdefault(topic, []).append(handler)

    def publish(self, topic: str, payload: dict[str, Any],
                headers: dict[str, Any] | None = None) -> None:
        """Queue a message for every handler subscribed to `topic`."""
        message = {"topic": topic, "payload": dict(payload),
                   "headers": dict(headers or {})}
        self.published.append(message)
        for handler in self._handlers.get(topic, []):
            self._pending.append((message, handler))

    def pending_count(self) -> int:
        """How many deliveries are waiting."""
        return len(self._pending)

    def run_pending(self) -> None:
        """Deliver every pending message once, including messages published
        by handlers during this call."""
        failed: list[tuple[dict[str, Any], Handler]] = []
        while self._pending:
            message, handler = self._pending.pop(0)
            try:
                handler({"topic": message["topic"],
                         "payload": dict(message["payload"]),
                         "headers": dict(message["headers"])})
            except Exception:  # noqa: BLE001 - the bus retries any failure
                failed.append((message, handler))
            else:
                self._delivered.append((message, handler))
        self._pending = failed

    def deliver_again(self) -> None:
        """Queue every delivered message again, as a duplicate."""
        self._pending.extend(self._delivered)
        self._delivered = []
