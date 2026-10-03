"""Persistent global admission budget for paid voice synthesis."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .db import Database, db


_MAX_GLOBAL_VOICE_CALLS_PER_HOUR = 120


def reserve_global_voice_call(database: Database = db, *, now: datetime | None = None) -> bool:
    """Atomically reserve one call within the previous rolling hour across app workers."""
    current = now or datetime.now(timezone.utc)
    current = current.astimezone(timezone.utc)
    timestamp = current.isoformat(timespec="microseconds")
    cutoff = (current - timedelta(hours=1)).isoformat(timespec="microseconds")

    with database._connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_call_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM voice_call_events WHERE created_at <= ?", (cutoff,))
        count = int(connection.execute("SELECT COUNT(*) FROM voice_call_events").fetchone()[0])
        if count >= _MAX_GLOBAL_VOICE_CALLS_PER_HOUR:
            return False
        connection.execute("INSERT INTO voice_call_events (created_at) VALUES (?)", (timestamp,))
        return True
