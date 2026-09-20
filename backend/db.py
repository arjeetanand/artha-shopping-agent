from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .settings import load_env


load_env()
ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("SHOPPINGHELP_DB_PATH", ROOT / "shoppinghelp.sqlite3"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def future_iso(days: int = 0, minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days, minutes=minutes)).isoformat(timespec="seconds")


def _session_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Database:
    def __init__(self, path: Path = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS searches (
                    id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    intent_json TEXT NOT NULL,
                    workflow_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    search_id TEXT,
                    status TEXT NOT NULL,
                    current_step INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    google_sub TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    picture TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE INDEX IF NOT EXISTS sessions_token_hash_index ON sessions(token_hash);

                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY,
                    code_verifier TEXT NOT NULL,
                    next_path TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS purchase_plans (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    search_id TEXT,
                    status TEXT NOT NULL,
                    total INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE INDEX IF NOT EXISTS purchase_plans_user_index ON purchase_plans(user_id, created_at DESC);
                """
            )

    def save_search(self, search_id: str, query: str, intent: dict[str, Any], workflow: list[dict[str, Any]]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO searches (id, query, intent_json, workflow_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (search_id, query, json.dumps(intent, ensure_ascii=False), json.dumps(workflow, ensure_ascii=False), now_iso()),
            )

    def upsert_google_user(self, *, google_sub: str, email: str, name: str, picture: str) -> dict[str, Any]:
        timestamp = now_iso()
        with self._connect() as connection:
            existing = connection.execute("SELECT id FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
            user_id = existing["id"] if existing else f"usr-{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO users (id, google_sub, email, name, picture, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(google_sub) DO UPDATE SET email=excluded.email, name=excluded.name, picture=excluded.picture, updated_at=excluded.updated_at
                """,
                (user_id, google_sub, email, name, picture, timestamp, timestamp),
            )
            row = connection.execute("SELECT id, email, name, picture FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row)

    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(48)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions (id, user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (f"ses-{uuid.uuid4().hex}", user_id, _session_hash(token), future_iso(days=7), now_iso()),
            )
        return token

    def get_user_for_session(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.email, users.name, users.picture
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                """,
                (_session_hash(token), now_iso()),
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, token: str) -> None:
        if token:
            with self._connect() as connection:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (_session_hash(token),))

    def save_oauth_state(self, state: str, code_verifier: str, next_path: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM oauth_states WHERE expires_at <= ?", (now_iso(),))
            connection.execute(
                "INSERT INTO oauth_states (state, code_verifier, next_path, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (state, code_verifier, next_path, future_iso(minutes=10), now_iso()),
            )

    def consume_oauth_state(self, state: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT code_verifier, next_path FROM oauth_states WHERE state = ? AND expires_at > ?", (state, now_iso())).fetchone()
            connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        return dict(row) if row else None

    def save_purchase_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO purchase_plans (id, user_id, search_id, status, total, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan["id"],
                    plan["user_id"],
                    plan.get("search_id"),
                    plan["status"],
                    plan["total"],
                    json.dumps(plan, ensure_ascii=False),
                    plan["created_at"],
                    plan["updated_at"],
                ),
            )
        return plan

    def list_purchase_plans(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload_json FROM purchase_plans WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]


db = Database()
