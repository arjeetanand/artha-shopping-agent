"""Private, daily-reset service logs for local connector diagnostics."""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_IST = timezone(timedelta(hours=5, minutes=30))
_LOCK = threading.Lock()
_SAFE_FIELDS = {
    "page", "pages", "card_count", "detail_link_count", "invoice_candidate_count",
    "invoice_count", "order_count", "item_count", "body_chars", "missing_dates",
    "unreadable_pages", "missing_invoices", "elapsed_ms", "http_status", "response_bytes",
    "history_exhausted", "coverage_complete", "window_limited", "auth_detected",
    "empty_state", "page_signature_duplicate", "scroll_changed", "has_next_page",
    "success", "retry_count", "cutoff", "until",
}
_SAFE_LABELS = {"error_code", "error_class", "outcome", "route"}


def _safe_details(details: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in details.items():
        if key in _SAFE_FIELDS and (isinstance(value, bool) or isinstance(value, int)):
            safe[key] = value
        elif key in {"cutoff", "until"} and isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            safe[key] = value
        elif key in _SAFE_LABELS and isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value):
            safe[key] = value
    return safe


def append_service_log(
    path: Path,
    *,
    service: str,
    run_id: str,
    step: str,
    status: str,
    details: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> None:
    """Append one redacted JSON event, clearing the file when its IST date changes."""
    now = (now or datetime.now(_IST)).astimezone(_IST)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    event = {
        "at": now.isoformat(timespec="seconds"),
        "service": service,
        "run_id": run_id,
        "step": step,
        "status": status,
        **_safe_details(details or {}),
    }
    line = (json.dumps(event, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")
    with _LOCK:
        if path.exists() and datetime.fromtimestamp(path.stat().st_mtime, _IST).date() != now.date():
            path.write_bytes(b"")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, line)
        finally:
            os.close(descriptor)
        os.utime(path, (now.timestamp(), now.timestamp()))
