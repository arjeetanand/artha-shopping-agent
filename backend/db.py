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
_SEARCH_RETENTION_DAYS = 7
_MAX_SEARCH_ROWS = 256
_MAX_SEARCH_RECORD_BYTES = 256 * 1024


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
                    products_json TEXT NOT NULL DEFAULT '[]',
                    source_json TEXT NOT NULL DEFAULT '{}',
                    server_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
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

                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    plan_id TEXT,
                    status TEXT NOT NULL,
                    total INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS payment_attempts (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_order_id TEXT NOT NULL UNIQUE,
                    amount INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE INDEX IF NOT EXISTS payment_attempts_user_index ON payment_attempts(user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS usage_events (
                    id TEXT PRIMARY KEY,
                    runtime TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    model TEXT,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    total_tokens INTEGER,
                    cached_tokens INTEGER,
                    input_characters INTEGER,
                    output_bytes INTEGER,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS usage_events_created_index ON usage_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS usage_events_runtime_index ON usage_events(runtime, created_at DESC);

                CREATE TABLE IF NOT EXISTS price_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_key TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    seller TEXT NOT NULL,
                    price INTEGER NOT NULL CHECK(price > 0),
                    currency TEXT NOT NULL,
                    source_status TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS price_observations_product_index
                ON price_observations(product_key, observed_at);
                """
            )
            order_columns = {row[1] for row in connection.execute("PRAGMA table_info(orders)").fetchall()}
            migrations = {
                "user_id": "TEXT",
                "plan_id": "TEXT",
                "currency": "TEXT NOT NULL DEFAULT 'INR'",
            }
            for column, definition in migrations.items():
                if column not in order_columns:
                    connection.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")
            connection.execute("CREATE INDEX IF NOT EXISTS orders_user_index ON orders(user_id, created_at DESC)")
            search_columns = {row[1] for row in connection.execute("PRAGMA table_info(searches)").fetchall()}
            if "products_json" not in search_columns:
                connection.execute("ALTER TABLE searches ADD COLUMN products_json TEXT NOT NULL DEFAULT '[]'")
            if "source_json" not in search_columns:
                connection.execute("ALTER TABLE searches ADD COLUMN source_json TEXT NOT NULL DEFAULT '{}'")
            if "server_verified" not in search_columns:
                connection.execute("ALTER TABLE searches ADD COLUMN server_verified INTEGER NOT NULL DEFAULT 0")
            self._prune_searches(connection, _MAX_SEARCH_ROWS)

    def _prune_searches(self, connection: sqlite3.Connection, max_rows: int) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_SEARCH_RETENTION_DAYS)).isoformat(timespec="seconds")
        referenced = "id IN (SELECT search_id FROM purchase_plans WHERE search_id IS NOT NULL)"
        connection.execute(f"DELETE FROM searches WHERE created_at < ? AND NOT {referenced}", (cutoff,))
        connection.execute(
            f"""
            DELETE FROM searches
            WHERE NOT {referenced}
              AND length(CAST(id AS BLOB))
                + length(CAST(query AS BLOB))
                + length(CAST(intent_json AS BLOB))
                + length(CAST(workflow_json AS BLOB))
                + length(CAST(products_json AS BLOB))
                + length(CAST(source_json AS BLOB)) > ?
            """,
            (_MAX_SEARCH_RECORD_BYTES,),
        )
        count = int(connection.execute("SELECT COUNT(*) FROM searches").fetchone()[0])
        excess = count - max_rows
        if excess <= 0:
            return
        oldest_unreferenced = connection.execute(
            f"SELECT id FROM searches WHERE NOT {referenced} ORDER BY created_at ASC, id ASC LIMIT ?",
            (excess,),
        ).fetchall()
        connection.executemany("DELETE FROM searches WHERE id = ?", [(row["id"],) for row in oldest_unreferenced])

    def save_search(
        self,
        search_id: str,
        query: str,
        intent: dict[str, Any],
        workflow: list[dict[str, Any]],
        products: list[dict[str, Any]] | None = None,
        source: dict[str, Any] | None = None,
    ) -> None:
        intent_json = json.dumps(intent, ensure_ascii=False)
        workflow_json = json.dumps(workflow, ensure_ascii=False)
        products_json = json.dumps(products or [], ensure_ascii=False)
        source_json = json.dumps(source or {}, ensure_ascii=False)
        row_size = sum(len(value.encode("utf-8")) for value in (search_id, query, intent_json, workflow_json, products_json, source_json))
        if row_size > _MAX_SEARCH_RECORD_BYTES:
            raise ValueError("Search result is too large to retain")
        with self._connect() as connection:
            already_exists = connection.execute("SELECT 1 FROM searches WHERE id = ?", (search_id,)).fetchone() is not None
            self._prune_searches(connection, _MAX_SEARCH_ROWS)
            already_exists = already_exists and connection.execute("SELECT 1 FROM searches WHERE id = ?", (search_id,)).fetchone() is not None
            self._prune_searches(connection, _MAX_SEARCH_ROWS if already_exists else _MAX_SEARCH_ROWS - 1)
            remaining = int(connection.execute("SELECT COUNT(*) FROM searches").fetchone()[0])
            if not already_exists and remaining >= _MAX_SEARCH_ROWS:
                raise RuntimeError("Search storage is at capacity; try again later.")
            connection.execute(
                "INSERT OR REPLACE INTO searches (id, query, intent_json, workflow_json, products_json, source_json, server_verified, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (
                    search_id,
                    query,
                    intent_json,
                    workflow_json,
                    products_json,
                    source_json,
                    now_iso(),
                ),
            )

    def get_search(self, search_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, query, intent_json, workflow_json, products_json, source_json, server_verified FROM searches WHERE id = ? AND created_at >= ?",
                (search_id, (datetime.now(timezone.utc) - timedelta(days=_SEARCH_RETENTION_DAYS)).isoformat(timespec="seconds")),
            ).fetchone()
        if not row:
            return None
        try:
            intent = json.loads(row["intent_json"])
            workflow = json.loads(row["workflow_json"])
            products = json.loads(row["products_json"])
            source = json.loads(row["source_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(intent, dict) or not isinstance(workflow, list) or not isinstance(products, list):
            return None
        if not isinstance(source, dict) or not source:
            mode = "clarification" if intent.get("clarifications") and not products else (
                "sandbox" if products and all(isinstance(product, dict) and product.get("source_kind") == "sandbox_catalog" for product in products) else "unknown"
            )
            source = {"mode": mode}
        return {"id": row["id"], "query": row["query"], "intent": intent, "trusted": bool(row["server_verified"]),
                "workflow": workflow, "products": products, "source": source}

    def get_search_products(self, search_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=_SEARCH_RETENTION_DAYS)).isoformat(timespec="seconds")
            row = connection.execute(
                "SELECT products_json, server_verified FROM searches WHERE id = ? AND (created_at >= ? OR id IN (SELECT search_id FROM purchase_plans WHERE search_id IS NOT NULL))",
                (search_id, cutoff),
            ).fetchone()
        if not row or not row["server_verified"]:
            return []
        try:
            products = json.loads(row["products_json"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return products if isinstance(products, list) else []

    def record_price_observations(self, observations: list[dict[str, Any]]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO price_observations
                (product_key, product_id, source_url, seller, price, currency, source_status, observed_at)
                VALUES (:product_key, :product_id, :source_url, :seller, :price, :currency, :source_status, :observed_at)
                """,
                observations,
            )

    def price_observations(self, product_key: str) -> list[dict[str, Any]]:
        if not product_key:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT product_id, source_url, seller, price, currency, source_status, observed_at
                FROM price_observations WHERE product_key = ? ORDER BY observed_at, id
                """,
                (product_key,),
            ).fetchall()
        return [dict(row) for row in rows]

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

    def get_purchase_plan(self, plan_id: str, user_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM purchase_plans WHERE id = ? AND user_id = ?",
                (plan_id, user_id),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def save_order(self, order: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO orders (id, user_id, plan_id, status, total, currency, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order["id"],
                    order["user_id"],
                    order.get("plan_id"),
                    order["status"],
                    order["total"],
                    order.get("currency") or "INR",
                    json.dumps(order, ensure_ascii=False),
                    order["created_at"],
                    order["updated_at"],
                ),
            )
        return order

    def list_orders(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM orders WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def get_order(self, order_id: str, user_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM orders WHERE id = ? AND user_id = ?",
                (order_id, user_id),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def update_order(self, order: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                "UPDATE orders SET status = ?, payload_json = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (
                    order["status"],
                    json.dumps(order, ensure_ascii=False),
                    order["updated_at"],
                    order["id"],
                    order["user_id"],
                ),
            )
        return order

    def save_payment_attempt(self, attempt: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO payment_attempts (
                    id, user_id, provider, provider_order_id, amount, currency,
                    status, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt["id"],
                    attempt["user_id"],
                    attempt["provider"],
                    attempt["provider_order_id"],
                    attempt["amount"],
                    attempt.get("currency") or "INR",
                    attempt["status"],
                    json.dumps(attempt, ensure_ascii=False),
                    attempt["created_at"],
                    attempt["updated_at"],
                ),
            )
        return attempt

    def get_payment_attempt(self, provider_order_id: str, user_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status, payload_json FROM payment_attempts WHERE provider_order_id = ? AND user_id = ?",
                (provider_order_id, user_id),
            ).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict):
            return None
        value["status"] = row["status"]
        return value

    def claim_payment_attempt(self, provider_order_id: str, user_id: str) -> dict[str, Any] | None:
        """Atomically let one verifier advance a created attempt."""
        # ponytail: a process crash can strand "verifying"; reconcile with Razorpay before allowing a retry.
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE payment_attempts SET status = 'verifying', updated_at = ? WHERE provider_order_id = ? AND user_id = ? AND status = 'created'",
                (now_iso(), provider_order_id, user_id),
            ).rowcount
            if not updated:
                return None
            row = connection.execute(
                "SELECT payload_json FROM payment_attempts WHERE provider_order_id = ? AND user_id = ?",
                (provider_order_id, user_id),
            ).fetchone()
        try:
            attempt = json.loads(row["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(attempt, dict):
            return None
        attempt["status"] = "verifying"
        return attempt

    def update_payment_attempt(self, attempt: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                "UPDATE payment_attempts SET status = ?, payload_json = ?, updated_at = ? WHERE provider_order_id = ? AND user_id = ?",
                (
                    attempt["status"],
                    json.dumps(attempt, ensure_ascii=False),
                    attempt["updated_at"],
                    attempt["provider_order_id"],
                    attempt["user_id"],
                ),
            )
        return attempt

    def record_usage_event(self, event: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO usage_events (
                    id, runtime, provider, operation, model, input_tokens, output_tokens,
                    total_tokens, cached_tokens, input_characters, output_bytes, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["id"],
                    event["runtime"],
                    event["provider"],
                    event["operation"],
                    event.get("model") or None,
                    event.get("input_tokens"),
                    event.get("output_tokens"),
                    event.get("total_tokens"),
                    event.get("cached_tokens"),
                    event.get("input_characters"),
                    event.get("output_bytes"),
                    event.get("status") or "success",
                    event["created_at"],
                ),
            )

    def usage_summary(self, *, days: int = 30, runtime: str | None = None) -> dict[str, Any]:
        safe_days = max(1, min(int(days), 365))
        since = (datetime.now(timezone.utc) - timedelta(days=safe_days)).isoformat(timespec="seconds")
        where = ["created_at >= ?"]
        params: list[Any] = [since]
        if runtime in {"local", "production"}:
            where.append("runtime = ?")
            params.append(runtime)
        clause = " AND ".join(where)

        with self._connect() as connection:
            totals = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS requests,
                    COUNT(total_tokens) AS metered_requests,
                    COUNT(*) - COUNT(total_tokens) AS unmetered_requests,
                    SUM(input_tokens) AS input_tokens,
                    SUM(output_tokens) AS output_tokens,
                    SUM(total_tokens) AS total_tokens,
                    SUM(cached_tokens) AS cached_tokens,
                    SUM(input_characters) AS input_characters,
                    SUM(output_bytes) AS output_bytes
                FROM usage_events
                WHERE {clause}
                """,
                params,
            ).fetchone()
            by_provider = connection.execute(
                f"""
                SELECT
                    provider,
                    operation,
                    runtime,
                    COUNT(*) AS requests,
                    COUNT(total_tokens) AS metered_requests,
                    SUM(input_tokens) AS input_tokens,
                    SUM(output_tokens) AS output_tokens,
                    SUM(total_tokens) AS total_tokens,
                    SUM(cached_tokens) AS cached_tokens,
                    SUM(input_characters) AS input_characters,
                    SUM(output_bytes) AS output_bytes
                FROM usage_events
                WHERE {clause}
                GROUP BY provider, operation, runtime
                ORDER BY COALESCE(SUM(total_tokens), 0) DESC, requests DESC, provider ASC
                """,
                params,
            ).fetchall()
            recent = connection.execute(
                f"""
                SELECT id, runtime, provider, operation, model, input_tokens, output_tokens,
                       total_tokens, cached_tokens, input_characters, output_bytes, status, created_at
                FROM usage_events
                WHERE {clause}
                ORDER BY created_at DESC
                LIMIT 24
                """,
                params,
            ).fetchall()

        def row_dict(row: sqlite3.Row) -> dict[str, Any]:
            return dict(row)

        return {
            "window_days": safe_days,
            "filter_runtime": runtime or "all",
            "totals": row_dict(totals),
            "by_provider": [row_dict(row) for row in by_provider],
            "recent": [row_dict(row) for row in recent],
        }


db = Database()
