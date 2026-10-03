"""Persistent global admission budget for paid voice synthesis."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .db import Database, db


_MAX_GLOBAL_VOICE_CALLS_PER_HOUR = 120


def reserve_global_voice_call(database: Database = db, *, now: datetime | None = None) -> bool:
    """Atomically reserve one call in the current UTC hour across app workers."""
    current = now or datetime.now(timezone.utc)
    current = current.astimezone(timezone.utc)
    window_start = current.replace(minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
    retention_cutoff = (current - timedelta(days=1)).isoformat(timespec="seconds")

    with database._connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_call_budget (
                window_start TEXT PRIMARY KEY,
                request_count INTEGER NOT NULL CHECK(request_count >= 0)
            )
            """
        )
        connection.execute("DELETE FROM voice_call_budget WHERE window_start < ?", (retention_cutoff,))
        reservation = connection.execute(
            """
            INSERT INTO voice_call_budget (window_start, request_count) VALUES (?, 1)
            ON CONFLICT(window_start) DO UPDATE SET request_count = request_count + 1
            WHERE request_count < ?
            """,
            (window_start, _MAX_GLOBAL_VOICE_CALLS_PER_HOUR),
        )
        return reservation.rowcount == 1
