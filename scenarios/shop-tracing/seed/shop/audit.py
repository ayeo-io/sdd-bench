"""The audit trail. Kept separately from the log and never deleted."""

from __future__ import annotations

from typing import Any

ENTRIES: list[dict[str, Any]] = []


def record(action: str, **fields: Any) -> None:
    """Add an entry to the audit trail."""
    ENTRIES.append({"action": action, **fields})


def clear() -> None:
    """Forget every entry. For tests."""
    ENTRIES.clear()
