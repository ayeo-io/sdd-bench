"""The user service: who our customers are."""

from __future__ import annotations

import itertools
from typing import Any

from shop.bus import Bus
from shop.errors import UnknownUser
from shop.log import log
from shop.store import Store

_ids = itertools.count(1)


class UserService:
    """Holds each user's name and email, the only personal data in the shop."""

    def __init__(self, bus: Bus) -> None:
        self.bus = bus
        self.store = Store()

    def create_user(self, name: str, email: str) -> str:
        """Add a user and announce it with `user.created`. Returns the user id."""
        user_id = f"u{next(_ids)}"
        self.store.put(user_id, {"name": name, "email": email})
        log("users", "user.created", user_id=user_id)
        self.bus.publish("user.created", {"user_id": user_id})
        return user_id

    def get_user(self, user_id: str) -> dict[str, Any]:
        """Return the user's id, name and email. Raises UnknownUser."""
        row = self.store.get(user_id)
        if row is None:
            raise UnknownUser(user_id)
        return {"user_id": user_id, **row}
