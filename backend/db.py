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
_PRICE_OBSERVATION_RETENTION_DAYS = 90
_MAX_PRICE_OBSERVATION_ROWS = 10_000
_MAX_PRICE_OBSERVATIONS_PER_PRODUCT = 256
_MAX_PRICE_OBSERVATIONS_PER_BATCH = 256
_USAGE_EVENT_RETENTION_DAYS = 365
_MAX_USAGE_EVENT_ROWS = 100_000


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
                    purpose TEXT NOT NULL DEFAULT 'signin',
                    user_id TEXT,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gmail_tokens (
                    user_id TEXT PRIMARY KEY,
                    account_email TEXT NOT NULL,
                    refresh_token_ciphertext TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gmail_imports (
                    user_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT '',
                    result TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, message_id)
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

                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    preferences_json TEXT NOT NULL DEFAULT '{}',
                    stats_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS account_connections (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    account_email TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'connected',
                    synced_orders_count INTEGER NOT NULL DEFAULT 0,
                    last_synced_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, provider)
                );

                CREATE TABLE IF NOT EXISTS taste_memories (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    source_url TEXT NOT NULL DEFAULT '',
                    document TEXT NOT NULL,
                    attributes_json TEXT NOT NULL DEFAULT '{}',
                    embedding_json TEXT,
                    embedding_model TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, source_key)
                );
                CREATE INDEX IF NOT EXISTS taste_memory_user_index ON taste_memories(user_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS retailer_invoices (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    retailer_order_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    extracted_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, provider, retailer_order_id, sha256)
                );

                CREATE TABLE IF NOT EXISTS instagram_references (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    friend_name TEXT NOT NULL DEFAULT '',
                    handle TEXT NOT NULL DEFAULT '',
                    post_url TEXT NOT NULL,
                    shortcode TEXT NOT NULL DEFAULT '',
                    caption TEXT NOT NULL DEFAULT '',
                    screenshot_path TEXT NOT NULL DEFAULT '',
                    captured_at TEXT NOT NULL,
                    attributes_json TEXT NOT NULL DEFAULT '{}',
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(user_id, post_url)
                );
                CREATE INDEX IF NOT EXISTS instagram_references_user_index ON instagram_references(user_id, captured_at DESC);

                CREATE TABLE IF NOT EXISTS conversation_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    messages_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS conversation_sessions_user_index ON conversation_sessions(user_id, updated_at DESC);
                """
            )
            connection_columns = {row[1] for row in connection.execute("PRAGMA table_info(account_connections)").fetchall()}
            if "details_json" not in connection_columns:
                connection.execute("ALTER TABLE account_connections ADD COLUMN details_json TEXT NOT NULL DEFAULT '{}'")
            oauth_columns = {row[1] for row in connection.execute("PRAGMA table_info(oauth_states)").fetchall()}
            for column, definition in {"purpose": "TEXT NOT NULL DEFAULT 'signin'", "user_id": "TEXT"}.items():
                if column not in oauth_columns:
                    connection.execute(f"ALTER TABLE oauth_states ADD COLUMN {column} {definition}")
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
            self._prune_price_observations(connection, _MAX_PRICE_OBSERVATION_ROWS)
            self._prune_usage_events(connection, _MAX_USAGE_EVENT_ROWS)

    def _prune_searches(self, connection: sqlite3.Connection, max_rows: int) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_SEARCH_RETENTION_DAYS)).isoformat(timespec="seconds")
        unreferenced = "id NOT IN (SELECT search_id FROM purchase_plans WHERE search_id IS NOT NULL)"
        connection.execute(f"DELETE FROM searches WHERE created_at < ? AND {unreferenced}", (cutoff,))
        connection.execute(
            f"""
            DELETE FROM searches
            WHERE {unreferenced}
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
            f"SELECT id FROM searches WHERE {unreferenced} ORDER BY created_at ASC, id ASC LIMIT ?",
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

    def _prune_price_observations(self, connection: sqlite3.Connection, max_rows: int) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_PRICE_OBSERVATION_RETENTION_DAYS)).isoformat(timespec="seconds")
        connection.execute(
            """
            DELETE FROM price_observations
            WHERE observed_at < ?
               OR length(CAST(product_key AS BLOB)) > 2048
               OR length(CAST(product_id AS BLOB)) > 256
               OR length(CAST(source_url AS BLOB)) > 2048
               OR length(CAST(seller AS BLOB)) > 256
               OR length(CAST(currency AS BLOB)) > 8
               OR length(CAST(source_status AS BLOB)) > 64
               OR length(CAST(observed_at AS BLOB)) > 40
            """,
            (cutoff,),
        )
        connection.execute(
            """
            DELETE FROM price_observations
            WHERE id IN (
                SELECT id FROM price_observations
                ORDER BY observed_at DESC, id DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (max_rows,),
        )
        connection.execute(
            """
            DELETE FROM price_observations
            WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY product_key ORDER BY observed_at DESC, id DESC
                    ) AS product_rank
                    FROM price_observations
                ) WHERE product_rank > ?
            )
            """,
            (_MAX_PRICE_OBSERVATIONS_PER_PRODUCT,),
        )

    def _prune_usage_events(self, connection: sqlite3.Connection, max_rows: int) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_USAGE_EVENT_RETENTION_DAYS)).isoformat(timespec="seconds")
        connection.execute("DELETE FROM usage_events WHERE created_at < ?", (cutoff,))
        connection.execute(
            """
            DELETE FROM usage_events
            WHERE id IN (
                SELECT id FROM usage_events
                ORDER BY created_at DESC, id DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (max_rows,),
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

    def get_latest_search(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=_SEARCH_RETENTION_DAYS)).isoformat(timespec="seconds")
            row = connection.execute(
                "SELECT id, query, intent_json, workflow_json, products_json, source_json, server_verified FROM searches WHERE created_at >= ? ORDER BY created_at DESC LIMIT 1",
                (cutoff,),
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
        return {"id": row["id"], "query": row["query"], "intent": intent, "trusted": bool(row["server_verified"]),
                "workflow": workflow, "products": products, "source": source or {}}

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
        bounded: list[dict[str, Any]] = []
        for observation in observations[:_MAX_PRICE_OBSERVATIONS_PER_BATCH]:
            if not isinstance(observation, dict):
                continue
            values = {
                field: str(observation.get(field) or "")
                for field in ("product_key", "product_id", "source_url", "seller", "currency", "source_status", "observed_at")
            }
            field_limits = {"product_key": 2048, "product_id": 256, "source_url": 2048, "seller": 256,
                            "currency": 8, "source_status": 64, "observed_at": 40}
            if any(len(values[field].encode("utf-8")) > limit for field, limit in field_limits.items()):
                continue
            price = observation.get("price")
            if not values["product_key"] or not values["source_url"] or isinstance(price, bool) or not isinstance(price, int) or not 0 < price <= 2**63 - 1:
                continue
            bounded.append({**values, "price": price})
        if not bounded:
            return
        bounded.sort(key=lambda row: (row["observed_at"], row["product_key"], row["source_url"]))
        bounded = bounded[-_MAX_PRICE_OBSERVATION_ROWS:]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._prune_price_observations(connection, _MAX_PRICE_OBSERVATION_ROWS)
            current_count = int(connection.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0])
            excess = current_count + len(bounded) - _MAX_PRICE_OBSERVATION_ROWS
            if excess > 0:
                connection.execute(
                    "DELETE FROM price_observations WHERE id IN (SELECT id FROM price_observations ORDER BY observed_at ASC, id ASC LIMIT ?)",
                    (excess,),
                )
            connection.executemany(
                """
                INSERT INTO price_observations
                (product_key, product_id, source_url, seller, price, currency, source_status, observed_at)
                VALUES (:product_key, :product_id, :source_url, :seller, :price, :currency, :source_status, :observed_at)
                """,
                bounded,
            )
            self._prune_price_observations(connection, _MAX_PRICE_OBSERVATION_ROWS)

    def price_observations(self, product_key: str) -> list[dict[str, Any]]:
        if not product_key:
            return []
        with self._connect() as connection:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=_PRICE_OBSERVATION_RETENTION_DAYS)).isoformat(timespec="seconds")
            rows = connection.execute(
                """
                SELECT product_id, source_url, seller, price, currency, source_status, observed_at
                FROM price_observations WHERE product_key = ? AND observed_at >= ? ORDER BY observed_at DESC, id DESC LIMIT ?
                """,
                (product_key, cutoff, _MAX_PRICE_OBSERVATIONS_PER_PRODUCT),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

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

    def save_oauth_state(self, state: str, code_verifier: str, next_path: str, *, purpose: str = "signin", user_id: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM oauth_states WHERE expires_at <= ?", (now_iso(),))
            connection.execute(
                "INSERT INTO oauth_states (state, code_verifier, next_path, purpose, user_id, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (state, code_verifier, next_path, purpose, user_id, future_iso(minutes=10), now_iso()),
            )

    def oauth_state_purpose(self, state: str) -> str:
        with self._connect() as connection:
            row = connection.execute("SELECT purpose FROM oauth_states WHERE state = ? AND expires_at > ?", (state, now_iso())).fetchone()
        return str(row["purpose"] or "") if row else ""

    def consume_oauth_state(self, state: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT code_verifier, next_path, purpose, user_id FROM oauth_states WHERE state = ? AND expires_at > ?", (state, now_iso())).fetchone()
            connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        return dict(row) if row else None

    def save_gmail_token(self, user_id: str, account_email: str, ciphertext: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO gmail_tokens (user_id, account_email, refresh_token_ciphertext, updated_at)
                   VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET
                   account_email=excluded.account_email, refresh_token_ciphertext=excluded.refresh_token_ciphertext,
                   updated_at=excluded.updated_at""",
                (user_id, account_email, ciphertext, now_iso()),
            )

    def get_gmail_token(self, user_id: str) -> dict[str, str] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT account_email, refresh_token_ciphertext FROM gmail_tokens WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def delete_gmail_token(self, user_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM gmail_tokens WHERE user_id=?", (user_id,))

    def has_gmail_import(self, user_id: str, message_id: str) -> bool:
        with self._connect() as connection:
            return connection.execute("SELECT 1 FROM gmail_imports WHERE user_id=? AND message_id=?", (user_id, message_id)).fetchone() is not None

    def save_gmail_import(self, user_id: str, message_id: str, provider: str, result: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO gmail_imports (user_id, message_id, provider, result, imported_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, message_id, provider, result, now_iso()),
            )

    def save_purchase_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            search_id = str(plan.get("search_id") or "").strip()
            connection.execute("BEGIN IMMEDIATE")
            cutoff = (datetime.now(timezone.utc) - timedelta(days=_SEARCH_RETENTION_DAYS)).isoformat(timespec="seconds")
            search = connection.execute(
                "SELECT 1 FROM searches WHERE id = ? AND server_verified = 1 AND (created_at >= ? OR id IN (SELECT search_id FROM purchase_plans WHERE search_id IS NOT NULL))",
                (search_id, cutoff),
            ).fetchone()
            if not search:
                raise ValueError("Saved search expired before the purchase plan could be saved; run the search again")
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
                INSERT OR REPLACE INTO orders (id, user_id, plan_id, status, total, currency, payload_json, created_at, updated_at)
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
            connection.execute("BEGIN IMMEDIATE")
            self._prune_usage_events(connection, _MAX_USAGE_EVENT_ROWS)
            count = int(connection.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0])
            if count >= _MAX_USAGE_EVENT_ROWS:
                connection.execute(
                    "DELETE FROM usage_events WHERE id = (SELECT id FROM usage_events ORDER BY created_at ASC, id ASC LIMIT 1)"
                )
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

    def get_user_profile(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT preferences_json, stats_json, updated_at FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "user_id": user_id,
            "preferences": json.loads(row["preferences_json"]),
            "stats": json.loads(row["stats_json"]),
            "updated_at": row["updated_at"],
        }

    def save_user_profile(self, user_id: str, preferences: dict[str, Any], stats: dict[str, Any] | None = None) -> dict[str, Any]:
        updated_at = now_iso()
        stats_data = stats or {}
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_profiles (user_id, preferences_json, stats_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    preferences_json = excluded.preferences_json,
                    stats_json = excluded.stats_json,
                    updated_at = excluded.updated_at
                """,
                (user_id, json.dumps(preferences), json.dumps(stats_data), updated_at),
            )
        return {
            "user_id": user_id,
            "preferences": preferences,
            "stats": stats_data,
            "updated_at": updated_at,
        }

    def list_account_connections(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, provider, account_email, status, synced_orders_count, last_synced_at, created_at, details_json FROM account_connections WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [{**dict(row), "details": json.loads(row["details_json"])} for row in rows]

    def save_account_connection(
        self,
        user_id: str,
        provider: str,
        account_email: str,
        synced_orders_count: int = 0,
        status: str = "connected",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = now_iso()
        conn_id = f"conn-{provider}-{uuid.uuid4().hex[:6]}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO account_connections (id, user_id, provider, account_email, status, synced_orders_count, last_synced_at, created_at, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, provider) DO UPDATE SET
                    account_email = excluded.account_email,
                    status = excluded.status,
                    synced_orders_count = excluded.synced_orders_count,
                    last_synced_at = excluded.last_synced_at,
                    details_json = excluded.details_json
                """,
                (conn_id, user_id, provider, account_email, status, synced_orders_count, now, now, json.dumps(details or {})),
            )
        return next(item for item in self.list_account_connections(user_id) if item["provider"] == provider)

    def save_taste_memory(self, user_id: str, source_key: str, kind: str, document: str,
                          attributes: dict[str, Any], source_url: str = "", embedding: list[float] | None = None,
                          embedding_model: str = "") -> dict[str, Any]:
        memory_id = "mem-" + hashlib.sha256(f"{user_id}:{source_key}".encode()).hexdigest()[:32]
        timestamp = now_iso()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO taste_memories (id,user_id,source_key,kind,source_url,document,attributes_json,embedding_json,embedding_model,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(user_id,source_key) DO UPDATE SET
                     kind=excluded.kind,source_url=excluded.source_url,document=excluded.document,
                     attributes_json=excluded.attributes_json,embedding_json=excluded.embedding_json,
                     embedding_model=excluded.embedding_model,updated_at=excluded.updated_at""",
                (memory_id,user_id,source_key,kind,source_url,document,json.dumps(attributes),
                 json.dumps(embedding) if embedding else None,embedding_model,timestamp,timestamp),
            )
        return {"id": memory_id, "kind": kind, "source_key": source_key, "embedding_status": "ready" if embedding else "pending"}

    def list_taste_memories(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM taste_memories WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [{**dict(row), "attributes": json.loads(row["attributes_json"]),
                 "embedding": json.loads(row["embedding_json"]) if row["embedding_json"] else None} for row in rows]

    def delete_taste_memory(self, user_id: str, memory_id: str) -> bool:
        with self._connect() as connection:
            return bool(connection.execute("DELETE FROM taste_memories WHERE user_id=? AND id=?", (user_id,memory_id)).rowcount)

    def save_retailer_invoice(self, user_id: str, provider: str, retailer_order_id: str,
                             relative_path: str, sha256: str, extracted_text: str = "") -> dict[str, Any]:
        invoice_id = "inv-" + hashlib.sha256(f"{user_id}:{provider}:{retailer_order_id}:{sha256}".encode()).hexdigest()[:32]
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO retailer_invoices VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(user_id,provider,retailer_order_id,sha256) DO UPDATE SET extracted_text=excluded.extracted_text""",
                (invoice_id,user_id,provider,retailer_order_id,relative_path,sha256,extracted_text[:200000],now_iso()),
            )
        return {"id": invoice_id, "provider": provider, "retailer_order_id": retailer_order_id}

    def list_retailer_invoices(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id,provider,retailer_order_id,created_at FROM retailer_invoices WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_retailer_invoice(self, user_id: str, invoice_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM retailer_invoices WHERE user_id=? AND id=?", (user_id,invoice_id)).fetchone()
        return dict(row) if row else None

    def list_recent_searches(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, query, intent_json, created_at FROM searches ORDER BY created_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            try:
                intent = json.loads(row["intent_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(intent, dict):
                results.append({"id": row["id"], "query": row["query"], "intent": intent, "created_at": row["created_at"]})
        return results

    def save_instagram_reference(self, record: dict[str, Any]) -> dict[str, Any]:
        ref_id = str(record.get("id") or ("igref-" + hashlib.sha256(f"{record['user_id']}:{record['post_url']}".encode()).hexdigest()[:24]))
        captured_at = str(record.get("captured_at") or now_iso())
        attrs = record.get("attributes") if isinstance(record.get("attributes"), dict) else {}
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO instagram_references (
                    id, user_id, friend_name, handle, post_url, shortcode, caption,
                    screenshot_path, captured_at, attributes_json, confirmed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, post_url) DO UPDATE SET
                    friend_name = CASE WHEN excluded.friend_name != '' THEN excluded.friend_name ELSE instagram_references.friend_name END,
                    handle = CASE WHEN excluded.handle != '' THEN excluded.handle ELSE instagram_references.handle END,
                    shortcode = CASE WHEN excluded.shortcode != '' THEN excluded.shortcode ELSE instagram_references.shortcode END,
                    caption = CASE WHEN excluded.caption != '' THEN excluded.caption ELSE instagram_references.caption END,
                    screenshot_path = CASE WHEN excluded.screenshot_path != '' THEN excluded.screenshot_path ELSE instagram_references.screenshot_path END,
                    captured_at = excluded.captured_at,
                    attributes_json = excluded.attributes_json,
                    confirmed = excluded.confirmed
                """,
                (
                    ref_id,
                    str(record["user_id"]),
                    str(record.get("friend_name") or ""),
                    str(record.get("handle") or ""),
                    str(record["post_url"]),
                    str(record.get("shortcode") or ""),
                    str(record.get("caption") or "")[:4000],
                    str(record.get("screenshot_path") or ""),
                    captured_at,
                    json.dumps(attrs, ensure_ascii=False),
                    1 if record.get("confirmed") else 0,
                ),
            )
        return self.get_instagram_reference(ref_id, str(record["user_id"])) or {**record, "id": ref_id, "captured_at": captured_at, "attributes": attrs}

    def get_instagram_reference(self, ref_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        with self._connect() as connection:
            if user_id:
                row = connection.execute(
                    "SELECT * FROM instagram_references WHERE id = ? AND user_id = ?",
                    (ref_id, user_id),
                ).fetchone()
            else:
                row = connection.execute("SELECT * FROM instagram_references WHERE id = ?", (ref_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["attributes"] = json.loads(data.pop("attributes_json", "{}") or "{}")
        data["confirmed"] = bool(data.get("confirmed"))
        return data

    def list_instagram_references(self, user_id: str, handle: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if handle:
                rows = connection.execute(
                    "SELECT * FROM instagram_references WHERE user_id = ? AND lower(handle) = lower(?) ORDER BY captured_at DESC LIMIT ?",
                    (user_id, handle.lstrip("@"), max(1, min(int(limit), 50))),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM instagram_references WHERE user_id = ? ORDER BY captured_at DESC LIMIT ?",
                    (user_id, max(1, min(int(limit), 50))),
                ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["attributes"] = json.loads(item.pop("attributes_json", "{}") or "{}")
            item["confirmed"] = bool(item.get("confirmed"))
            out.append(item)
        return out

    def save_conversation_session(self, session_id: str, user_id: str, state: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
        timestamp = now_iso()
        with self._connect() as connection:
            existing = connection.execute("SELECT created_at FROM conversation_sessions WHERE id = ?", (session_id,)).fetchone()
            created_at = existing["created_at"] if existing else timestamp
            connection.execute(
                """
                INSERT INTO conversation_sessions (id, user_id, state_json, messages_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    user_id = excluded.user_id,
                    state_json = excluded.state_json,
                    messages_json = excluded.messages_json,
                    updated_at = excluded.updated_at
                """,
                (session_id, user_id, json.dumps(state, ensure_ascii=False), json.dumps(messages, ensure_ascii=False), created_at, timestamp),
            )
        return {"id": session_id, "user_id": user_id, "state": state, "messages": messages, "created_at": created_at, "updated_at": timestamp}

    def get_conversation_session(self, session_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        with self._connect() as connection:
            if user_id:
                row = connection.execute("SELECT * FROM conversation_sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
            else:
                row = connection.execute("SELECT * FROM conversation_sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "state": json.loads(row["state_json"] or "{}"),
            "messages": json.loads(row["messages_json"] or "[]"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_conversation_sessions(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM conversation_sessions WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                (user_id, max(1, min(int(limit), 50))),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "state": json.loads(row["state_json"] or "{}"),
                "messages": json.loads(row["messages_json"] or "[]"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def get_default_local_user(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, email, name, picture, updated_at FROM users ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None


db = Database()
