"""An in-memory key-value store. Each service owns one; no service reads
another's.

`fail_next_write()` makes the next write or delete raise StoreError, the
way a real database can fail part-way through a request.
"""

from __future__ import annotations

from typing import Any

from shop.errors import StoreError


class Store:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._fail_next = False

    def fail_next_write(self) -> None:
        self._fail_next = True

    def _check(self) -> None:
        if self._fail_next:
            self._fail_next = False
            raise StoreError("write failed")

    def put(self, key: str, row: dict[str, Any]) -> None:
        self._check()
        self._rows[key] = dict(row)

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._rows.get(key)
        return dict(row) if row is not None else None

    def delete(self, key: str) -> None:
        self._check()
        self._rows.pop(key, None)

    def items(self) -> list[tuple[str, dict[str, Any]]]:
        return [(k, dict(v)) for k, v in sorted(self._rows.items())]
