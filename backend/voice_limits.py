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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_budget_migrations (
                name TEXT PRIMARY KEY,
                completed_at TEXT NOT NULL
            )
            """
        )
        connection.execute("BEGIN IMMEDIATE")
        migration = connection.execute(
            "SELECT 1 FROM voice_budget_migrations WHERE name = 'hourly-counter-to-rolling-events'"
        ).fetchone()
        if not migration:
            legacy_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'voice_call_budget'"
            ).fetchone()
            if legacy_table:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(voice_call_budget)").fetchall()}
                if {"window_start", "request_count"}.issubset(columns):
                    current_bucket = current.replace(minute=0, second=0, microsecond=0)
                    recent_bucket = (current_bucket - timedelta(hours=1)).isoformat(timespec="seconds")
                    current_bucket_start = current_bucket.isoformat(timespec="seconds")
                    legacy_rows = connection.execute(
                        "SELECT window_start, request_count FROM voice_call_budget WHERE window_start >= ? AND window_start <= ?",
                        (recent_bucket, current_bucket_start),
                    ).fetchall()
                    previous_bucket_used = sum(
                        max(0, int(row["request_count"])) for row in legacy_rows
                        if row["window_start"] < current_bucket_start
                    )
                    current_bucket_used = sum(
                        max(0, int(row["request_count"])) for row in legacy_rows
                        if row["window_start"] >= current_bucket_start
                    )
                    current_used = min(_MAX_GLOBAL_VOICE_CALLS_PER_HOUR, current_bucket_used)
                    previous_used = min(_MAX_GLOBAL_VOICE_CALLS_PER_HOUR - current_used, previous_bucket_used)
                    connection.executemany(
                        "INSERT INTO voice_call_events (created_at) VALUES (?)",
                        [(current_bucket_start,)] * previous_used + [(timestamp,)] * current_used,
                    )
            connection.execute(
                "INSERT INTO voice_budget_migrations (name, completed_at) VALUES (?, ?)",
                ("hourly-counter-to-rolling-events", timestamp),
            )
        connection.execute("DELETE FROM voice_call_events WHERE created_at <= ?", (cutoff,))
        count = int(connection.execute("SELECT COUNT(*) FROM voice_call_events").fetchone()[0])
        if count >= _MAX_GLOBAL_VOICE_CALLS_PER_HOUR:
            return False
        connection.execute("INSERT INTO voice_call_events (created_at) VALUES (?)", (timestamp,))
        return True
