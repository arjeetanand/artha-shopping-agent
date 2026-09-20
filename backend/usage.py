"""Persistent provider usage accounting for the Artha runtime dashboard."""

from __future__ import annotations

import uuid
from typing import Any

from .db import db, now_iso
from .settings import is_production


def runtime_name() -> str:
    return "production" if is_production() else "local"


def _integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def record_usage(
    provider: str,
    operation: str,
    *,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    cached_tokens: int | None = None,
    input_characters: int | None = None,
    output_bytes: int | None = None,
    status: str = "success",
) -> None:
    """Record best-effort usage without allowing accounting to break a user request."""
    try:
        input_value = _integer(input_tokens)
        output_value = _integer(output_tokens)
        total_value = _integer(total_tokens)
        if total_value is None and input_value is not None and output_value is not None:
            total_value = input_value + output_value
        db.record_usage_event(
            {
                "id": f"usage-{uuid.uuid4().hex}",
                "runtime": runtime_name(),
                "provider": str(provider or "unknown")[:80],
                "operation": str(operation or "unknown")[:120],
                "model": str(model or "")[:160] or None,
                "input_tokens": input_value,
                "output_tokens": output_value,
                "total_tokens": total_value,
                "cached_tokens": _integer(cached_tokens),
                "input_characters": _integer(input_characters),
                "output_bytes": _integer(output_bytes),
                "status": str(status or "success")[:40],
                "created_at": now_iso(),
            }
        )
    except Exception:
        # Usage is an observability feature; a locked or unavailable ledger must
        # never turn a successful provider response into a failed user request.
        return


def get_usage_summary(*, days: int = 30, runtime: str | None = None) -> dict[str, Any]:
    return db.usage_summary(days=days, runtime=runtime)
