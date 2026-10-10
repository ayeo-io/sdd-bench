"""An in-memory key-value store. Each service owns one; no service reads
another's.

A write can fail part-way through a request, the way a real database can.
`fail_next_write()` makes the next write or delete raise StoreError;
`fail_write_after(n)` lets n writes succeed and fails the one after.
A failed write changes nothing.

`rows_read` counts every row a read returns, the way a database bills
reads; operators watch it to catch requests that scan a whole table.
"""

from __future__ import annotations

from typing import Any

from shop.errors import StoreError


class Store:
    """Rows of plain data, keyed by string."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._fail_in: int | None = None
        self.rows_read = 0

    def fail_next_write(self) -> None:
        """Make the next write or delete fail."""
        self.fail_write_after(0)

    def fail_write_after(self, successful_writes: int) -> None:
        """Let `successful_writes` writes succeed, then fail the next one."""
        self._fail_in = successful_writes

    def _check(self) -> None:
        if self._fail_in is None:
            return
        if self._fail_in == 0:
            self._fail_in = None
            raise StoreError("write failed")
        self._fail_in -= 1

    def put(self, key: str, row: dict[str, Any]) -> None:
        """Write a row, replacing any row with the same key."""
        self._check()
        self._rows[key] = dict(row)

    def get(self, key: str) -> dict[str, Any] | None:
        """Read a row, or None when there is no row with that key."""
        row = self._rows.get(key)
        if row is None:
            return None
        self.rows_read += 1
        return dict(row)

    def delete(self, key: str) -> None:
        """Delete a row. Deleting a missing key is not an error."""
        self._check()
        self._rows.pop(key, None)

    def items(self) -> list[tuple[str, dict[str, Any]]]:
        """Every row, in key order. Reads, and counts, the whole store."""
        self.rows_read += len(self._rows)
        return [(k, dict(v)) for k, v in sorted(self._rows.items())]
