"""Structured logging. Every record is a dict kept in RECORDS, so a test
or an operator can read the log back."""

from __future__ import annotations

from typing import Any

RECORDS: list[dict[str, Any]] = []


def log(service: str, event: str, **fields: Any) -> None:
    RECORDS.append({"service": service, "event": event, **fields})


def clear() -> None:
    RECORDS.clear()
