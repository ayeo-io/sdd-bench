"""Trace ids: one per request, carried in every log record and event the
request causes, so the request can be followed through every service."""

from __future__ import annotations

import uuid
from typing import Any


def new_trace_id() -> str:
    """A fresh, unguessable trace id."""
    return uuid.uuid4().hex


def ensure(trace_id: str | None) -> str:
    """The given trace id, or a fresh one when none (or an empty one) is given."""
    return trace_id or new_trace_id()


def from_message(message: dict[str, Any]) -> str:
    """The trace id an incoming message carries, or a fresh one."""
    return ensure(message.get("headers", {}).get("trace_id"))


def headers(trace_id: str) -> dict[str, str]:
    """Event headers that carry the trace id."""
    return {"trace_id": trace_id}
