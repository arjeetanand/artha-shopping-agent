"""Focused regression checks for the security scan fixes."""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
import time
import uuid
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class Connection:
    def __init__(self) -> None:
        self.timeout = None

    def gettimeout(self):
        return self.timeout

    def settimeout(self, value) -> None:
        self.timeout = value


class Fragments:
    def __init__(self, chunks: list[bytes], connection: Connection, delay: float = 0) -> None:
        self.chunks = iter(chunks)
        self.connection = connection
        self.delay = delay

    def read1(self, size: int) -> bytes:
        if self.delay:
            timeout = self.connection.timeout
            time.sleep(min(self.delay, timeout))
            if self.delay >= timeout:
                raise socket.timeout()
        return next(self.chunks, b"")[:size]


class SecurityBoundaryContracts(unittest.TestCase):
    def test_social_reference_url_rejects_non_public_targets_and_redacts_query(self) -> None:
        from backend.social import _public_reference_url

        public_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        with patch("backend.social.socket.getaddrinfo", return_value=public_dns):
            self.assertEqual(
                _public_reference_url("https://example.com/post?token=secret#section"),
                ("https://example.com/post?token=secret#section", "https://example.com/post"),
            )

        for url in (
            "file:///etc/passwd",
            "http://localhost/",
            "http://127.0.0.1/",
            "https://example.com:8443/",
            "https://user:secret@example.com/",
            "https://example.com/" + ("a" * 2049),
        ):
            with self.subTest(url=url[:80]), self.assertRaises(ValueError):
                _public_reference_url(url)

        mixed_dns = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.2", 443)),
        ]
        with patch("backend.social.socket.getaddrinfo", return_value=mixed_dns):
            with self.assertRaises(ValueError):
                _public_reference_url("https://mixed.example/")

    def test_social_theme_does_not_send_query_tokens_to_model(self) -> None:
        from backend.social import extract_theme_from_url

        model = SimpleNamespace(
            provider="gemini",
            preference="gemini",
            gemini=SimpleNamespace(extract_brief=Mock(return_value={"theme": "minimal", "colors": ["black"]})),
        )
        dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        with (
            patch("backend.social.socket.getaddrinfo", return_value=dns),
            patch("backend.social.capture_social_page", return_value={
                "success": True,
                "title": "Look", "description": "Minimal outfit", "screenshot_base64": "aGVsbG8=", "mime_type": "image/jpeg",
            }),
            patch("backend.social.BriefModel", return_value=model),
        ):
            result = extract_theme_from_url("https://example.com/look?token=secret#private")

        self.assertEqual(result["url"], "https://example.com/look")
        prompt = model.gemini.extract_brief.call_args.args[0]
        self.assertNotIn("secret", prompt)
        self.assertNotIn("token", prompt)

    def test_production_session_cookie_cannot_disable_secure(self) -> None:
        from backend import auth

        for override in ("", "0", "false", "no"):
            with patch.dict(os.environ, {"APP_ENV": "production", "SHOPPINGHELP_COOKIE_SECURE": override}):
                self.assertIn("Secure", auth.session_cookie("token").split("; "))
                self.assertIn("Secure", auth.clear_session_cookie().split("; "))
        with patch.dict(os.environ, {"APP_ENV": "development", "SHOPPINGHELP_COOKIE_SECURE": "0"}):
            self.assertNotIn("Secure", auth.session_cookie("token").split("; "))
            self.assertNotIn("Secure", auth.clear_session_cookie().split("; "))
        with patch.dict(os.environ, {"APP_ENV": "development", "SHOPPINGHELP_COOKIE_SECURE": "1"}):
            self.assertIn("Secure", auth.session_cookie("token").split("; "))
            self.assertIn("Secure", auth.clear_session_cookie().split("; "))

    def test_oauth_state_cookie_binds_before_state_consumption(self) -> None:
        from backend import auth

        state = "a" * 43
        with patch.dict(os.environ, {"APP_ENV": "development", "SHOPPINGHELP_COOKIE_SECURE": "0"}):
            cookie = auth.oauth_state_cookie(state).split(";", 1)[0]
            self.assertTrue(auth.google_oauth_state_matches(cookie, state))
            self.assertFalse(auth.google_oauth_state_matches(None, state))
            self.assertFalse(auth.google_oauth_state_matches(f"artha_oauth_state_{state}={'b' * 43}", state))

            with patch.object(auth.db, "consume_oauth_state") as consume:
                with self.assertRaises(auth.AuthError):
                    auth.complete_google_auth("code", state, None)
                consume.assert_not_called()

                consume.return_value = None
                with self.assertRaises(auth.AuthError):
                    auth.complete_google_auth("code", state, cookie)
                consume.assert_called_once_with(state)

    def test_return_paths_and_redirect_sink_reject_header_controls(self) -> None:
        from backend import auth, server

        self.assertEqual(auth._safe_next("/plans?tab=saved"), "/plans?tab=saved")
        with self.assertRaises(auth.AuthError):
            auth._safe_next("/plans\r\nSet-Cookie: injected=1")

        handler = server.Handler.__new__(server.Handler)
        handler.send_response = Mock()
        with self.assertRaises(server.ApiError):
            server.Handler._redirect(handler, "/plans\r\nSet-Cookie: injected=1")
        handler.send_response.assert_not_called()

    def test_json_body_rejects_negative_length_and_keeps_zero_length_behavior(self) -> None:
        from backend import server

        connection = Connection()
        body = Fragments([b"{}"], connection)
        handler = SimpleNamespace(headers={"Content-Length": "-1"}, connection=connection, rfile=body)
        with self.assertRaises(server.ApiError) as error:
            server.Handler._read_json(handler)
        self.assertEqual(error.exception.status, 400)
        self.assertEqual(next(body.chunks, b""), b"{}")

        handler.headers = {"Content-Length": "0"}
        self.assertEqual(server.Handler._read_json(handler), {})

    def test_body_deadline_is_rechecked_between_partial_reads(self) -> None:
        from backend import server

        connection = Connection()
        body = Fragments([b"{", b"}", b" "], connection, delay=0.03)
        handler = SimpleNamespace(headers={"Content-Length": "3"}, connection=connection, rfile=body)
        started = time.monotonic()
        with patch.object(server, "_BODY_READ_TIMEOUT_SECONDS", 0.05):
            with self.assertRaises(server.ApiError) as error:
                server.Handler._read_json(handler)
        self.assertEqual(error.exception.status, 408)
        self.assertLess(time.monotonic() - started, 0.25)
        self.assertIsNone(connection.gettimeout())

    def test_guest_search_admission_is_shared_and_bounded(self) -> None:
        from backend import jobs, server

        client = f"test-{uuid.uuid4().hex}"
        self.assertTrue(all(jobs.allow_search_request(client) for _ in range(20)))
        self.assertFalse(jobs.allow_search_request(client))

        semaphore = server._SEARCH_REQUEST_CAPACITY
        acquired = 0
        while semaphore.acquire(blocking=False):
            acquired += 1
        self.assertEqual(acquired, 8)
        try:
            with patch.object(server, "allow_search_request", return_value=True):
                for path in ("/api/agent/search", "/api/agent/refine", "/api/agent/search/jobs"):
                    response = []
                    handler = server.Handler.__new__(server.Handler)
                    handler.path = path
                    handler.client_address = (client, 1234)
                    handler._read_json = Mock(side_effect=AssertionError("body read after admission denial"))
                    handler._send = lambda status, body: response.append(status)
                    server.Handler.do_POST(handler)
                    self.assertEqual(response, [503])
        finally:
            for _ in range(acquired):
                semaphore.release()

    def test_paid_voice_has_per_ip_and_concurrency_admission(self) -> None:
        from backend import server

        provider = SimpleNamespace(provider="elevenlabs", speak=Mock(return_value=(b"audio", "audio/mpeg")))

        def post_voice(client: str, text: str = "hello") -> list[int]:
            result: list[int] = []
            handler = server.Handler.__new__(server.Handler)
            handler.path = "/api/voice/speak"
            handler.client_address = (client, 1234)
            handler._read_json = Mock(return_value={"text": text})
            handler._send = lambda status, body: result.append(status)
            handler._send_bytes = lambda status, data, content_type: result.append(status)
            server.Handler.do_POST(handler)
            return result

        with (
            patch.object(server, "VoiceService", return_value=provider),
            patch.object(server, "reserve_global_voice_call", return_value=True),
            patch.object(server, "_VOICE_REQUESTS_PER_MINUTE", 1),
            patch.object(server, "_voice_admission_lock", threading.Lock()),
            patch.object(server, "_voice_requests_by_client", {}),
            patch.object(server, "_last_voice_client_cleanup", 0.0),
            patch.object(server, "_VOICE_CAPACITY", threading.BoundedSemaphore(2)),
        ):
            self.assertEqual(post_voice("192.0.2.10"), [200])
            self.assertEqual(post_voice("192.0.2.10"), [429])
            provider.speak.assert_called_once_with("hello")

        provider.speak.reset_mock()
        reserve_budget = Mock(return_value=True)
        with (
            patch.object(server, "VoiceService", return_value=provider),
            patch.object(server, "reserve_global_voice_call", reserve_budget),
            patch.object(server, "_voice_admission_lock", threading.Lock()),
            patch.object(server, "_voice_requests_by_client", {}),
            patch.object(server, "_last_voice_client_cleanup", 0.0),
            patch.object(server, "_VOICE_CAPACITY", threading.BoundedSemaphore(1)),
        ):
            self.assertEqual(post_voice("192.0.2.13", " \n  "), [400])
            reserve_budget.assert_not_called()
            provider.speak.assert_not_called()

        provider.speak.reset_mock()
        with (
            patch.object(server, "VoiceService", return_value=provider),
            patch.object(server, "reserve_global_voice_call", return_value=False),
            patch.object(server, "_voice_admission_lock", threading.Lock()),
            patch.object(server, "_voice_requests_by_client", {}),
            patch.object(server, "_last_voice_client_cleanup", 0.0),
            patch.object(server, "_VOICE_CAPACITY", threading.BoundedSemaphore(1)),
        ):
            self.assertEqual(post_voice("192.0.2.12"), [429])
            provider.speak.assert_not_called()

        provider.speak.reset_mock()
        capacity = threading.BoundedSemaphore(1)
        self.assertTrue(capacity.acquire(blocking=False))
        with (
            patch.object(server, "VoiceService", return_value=provider),
            patch.object(server, "_VOICE_CAPACITY", capacity),
            patch.object(server, "_voice_admission_lock", threading.Lock()),
            patch.object(server, "_voice_requests_by_client", {}),
            patch.object(server, "_last_voice_client_cleanup", 0.0),
        ):
            self.assertEqual(post_voice("192.0.2.11"), [503])
            provider.speak.assert_not_called()
        capacity.release()

    def test_social_theme_has_per_ip_and_concurrency_admission(self) -> None:
        from backend import server

        extractor = Mock(return_value={"theme": "minimal"})

        def post_theme(client: str) -> list[int]:
            result: list[int] = []
            handler = server.Handler.__new__(server.Handler)
            handler.path = "/api/social/theme"
            handler._user = lambda: None
            handler.client_address = (client, 1234)
            handler._read_json = Mock(return_value={"url": "https://example.com/look"})
            handler._send = lambda status, body: result.append(status)
            server.Handler.do_POST(handler)
            return result

        with (
            patch("backend.social.extract_theme_from_url", extractor),
            patch.object(server, "_SOCIAL_REQUESTS_PER_MINUTE", 1),
            patch.object(server, "_social_admission_lock", threading.Lock()),
            patch.object(server, "_social_requests_by_client", {}),
            patch.object(server, "_last_social_client_cleanup", 0.0),
            patch.object(server, "_SOCIAL_CAPACITY", threading.BoundedSemaphore(1)),
        ):
            self.assertEqual(post_theme("192.0.2.30"), [200])
            self.assertEqual(post_theme("192.0.2.30"), [429])
            extractor.assert_called_once_with("https://example.com/look")

        capacity = threading.BoundedSemaphore(1)
        self.assertTrue(capacity.acquire(blocking=False))
        with (
            patch("backend.social.extract_theme_from_url", extractor),
            patch.object(server, "_social_admission_lock", threading.Lock()),
            patch.object(server, "_social_requests_by_client", {}),
            patch.object(server, "_last_social_client_cleanup", 0.0),
            patch.object(server, "_SOCIAL_CAPACITY", capacity),
        ):
            result: list[int] = []
            handler = server.Handler.__new__(server.Handler)
            handler.path = "/api/social/theme"
            handler.client_address = ("192.0.2.31", 1234)
            handler._read_json = Mock(side_effect=AssertionError("body read after capacity denial"))
            handler._send = lambda status, body: result.append(status)
            server.Handler.do_POST(handler)
            self.assertEqual(result, [503])
            handler._read_json.assert_not_called()
        capacity.release()

    def test_slng_voice_uses_paid_voice_admission(self) -> None:
        from backend import server

        provider = SimpleNamespace(
            provider="slng",
            status=Mock(return_value={"configured": True}),
            speak=Mock(return_value=(b"audio", "audio/wav")),
        )
        response: list[int] = []
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/api/voice/speak"
        handler.client_address = ("192.0.2.14", 1234)
        handler._read_json = Mock(return_value={"text": "hello"})
        handler._send = lambda status, body: response.append(status)
        handler._send_bytes = lambda status, data, content_type: response.append(status)

        with (
            patch.object(server, "VoiceService", return_value=provider),
            patch.object(server, "reserve_global_voice_call", return_value=False) as reserve,
            patch.object(server, "_voice_admission_lock", threading.Lock()),
            patch.object(server, "_voice_requests_by_client", {}),
            patch.object(server, "_last_voice_client_cleanup", 0.0),
            patch.object(server, "_VOICE_CAPACITY", threading.BoundedSemaphore(1)),
        ):
            server.Handler.do_POST(handler)

        self.assertEqual(response, [429])
        reserve.assert_called_once()
        provider.speak.assert_not_called()

    def test_unconfigured_slng_voice_does_not_consume_paid_admission(self) -> None:
        from backend import server

        provider = SimpleNamespace(
            provider="slng", status=Mock(return_value={"configured": False}), speak=Mock(),
        )
        response: list[int] = []
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/api/voice/speak"
        handler.client_address = ("192.0.2.15", 1234)
        handler._read_json = Mock(return_value={"text": "hello"})
        handler._send = lambda status, body: response.append(status)
        handler._send_bytes = lambda status, data, content_type: response.append(status)

        with (
            patch.object(server, "VoiceService", return_value=provider),
            patch.object(server, "reserve_global_voice_call", return_value=True) as reserve,
            patch.object(server, "_voice_admission_lock", threading.Lock()),
            patch.object(server, "_voice_requests_by_client", {}),
            patch.object(server, "_last_voice_client_cleanup", 0.0),
            patch.object(server, "_VOICE_CAPACITY", threading.BoundedSemaphore(1)),
        ):
            server.Handler.do_POST(handler)

        self.assertEqual(response, [503])
        reserve.assert_not_called()
        provider.speak.assert_not_called()

    def test_global_paid_voice_budget_persists_across_database_instances(self) -> None:
        from datetime import datetime, timezone

        from backend import voice_limits
        from backend.db import Database

        with tempfile.TemporaryDirectory(prefix="artha-voice-budget-", dir="/private/tmp") as directory:
            database_path = Path(directory) / "voice-budget.sqlite3"
            database = Database(database_path)
            current_hour = datetime(2026, 10, 3, 12, 15, tzinfo=timezone.utc)
            with patch.object(voice_limits, "_MAX_GLOBAL_VOICE_CALLS_PER_HOUR", 2):
                self.assertTrue(voice_limits.reserve_global_voice_call(database, now=current_hour))
                self.assertTrue(voice_limits.reserve_global_voice_call(database, now=current_hour))
                self.assertFalse(voice_limits.reserve_global_voice_call(Database(database_path), now=current_hour))
                self.assertTrue(voice_limits.reserve_global_voice_call(database, now=current_hour.replace(hour=13)))

    def test_legacy_voice_budget_is_carried_into_rolling_limit(self) -> None:
        from datetime import datetime, timezone

        from backend import voice_limits
        from backend.db import Database

        with tempfile.TemporaryDirectory(prefix="artha-voice-budget-upgrade-", dir="/private/tmp") as directory:
            database = Database(Path(directory) / "voice-budget.sqlite3")
            current_time = datetime(2026, 10, 3, 12, 59, tzinfo=timezone.utc)
            previous_bucket = current_time.replace(hour=11, minute=0).isoformat(timespec="seconds")
            current_bucket = current_time.replace(minute=0).isoformat(timespec="seconds")
            with database._connect() as connection:
                connection.execute(
                    "CREATE TABLE voice_call_budget (window_start TEXT PRIMARY KEY, request_count INTEGER NOT NULL)"
                )
                connection.executemany(
                    "INSERT INTO voice_call_budget VALUES (?, ?)",
                    [(previous_bucket, 1), (current_bucket, 1)],
                )
            with patch.object(voice_limits, "_MAX_GLOBAL_VOICE_CALLS_PER_HOUR", 2):
                self.assertFalse(voice_limits.reserve_global_voice_call(database, now=current_time))
                # The previous fixed-hour bucket expires at the next boundary;
                # the current bucket remains in the rolling window.
                self.assertTrue(voice_limits.reserve_global_voice_call(database, now=current_time.replace(hour=13, minute=0)))

    def test_search_storage_expires_caps_and_preserves_plan_references(self) -> None:
        from backend import db as db_module
        from backend.db import Database, now_iso

        with tempfile.TemporaryDirectory(prefix="artha-search-retention-", dir="/private/tmp") as directory:
            database = Database(Path(directory) / "searches.sqlite3")
            with patch.object(db_module, "_MAX_SEARCH_ROWS", 2):
                database.save_search("expired", "old query", {}, [])
                database.save_search("plan-search", "saved query", {}, [], products=[{"id": "p1", "price": 10}])
                timestamp = now_iso()
                database.save_purchase_plan({
                    "id": "plan-1", "user_id": "user-1", "search_id": "plan-search",
                    "status": "ready", "total": 10, "items": [{"id": "p1", "price": 10}],
                    "created_at": timestamp, "updated_at": timestamp,
                })
                with database._connect() as connection:
                    connection.execute("UPDATE searches SET created_at = '2000-01-01T00:00:00+00:00'")
                database.save_search("newest", "new query", {}, [])
                timestamp = now_iso()
                database.save_purchase_plan({
                    "id": "plan-2", "user_id": "user-2", "search_id": "newest",
                    "status": "ready", "total": 0, "items": [],
                    "created_at": timestamp, "updated_at": timestamp,
                })
                with database._connect() as connection:
                    ids = {row["id"] for row in connection.execute("SELECT id FROM searches")}
                self.assertEqual(ids, {"plan-search", "newest"})
                self.assertIsNone(database.get_search("plan-search"))
                self.assertEqual(database.get_search_products("plan-search")[0]["id"], "p1")
                with self.assertRaises(RuntimeError):
                    database.save_search("overflow", "blocked", {}, [])
                with self.assertRaisesRegex(ValueError, "Saved search expired"):
                    database.save_purchase_plan({
                        "id": "plan-missing", "user_id": "user-3", "search_id": "missing",
                        "status": "ready", "total": 0, "items": [],
                        "created_at": timestamp, "updated_at": timestamp,
                    })

        with tempfile.TemporaryDirectory(prefix="artha-search-size-", dir="/private/tmp") as directory:
            database = Database(Path(directory) / "search-size.sqlite3")
            with patch.object(db_module, "_MAX_SEARCH_RECORD_BYTES", 32):
                with self.assertRaises(ValueError):
                    database.save_search("oversized", "x" * 40, {}, [])
                with database._connect() as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM searches").fetchone()[0], 0)

    def test_price_observation_storage_is_expiring_and_bounded(self) -> None:
        from datetime import datetime, timedelta, timezone

        from backend import db as db_module
        from backend.db import Database

        with tempfile.TemporaryDirectory(prefix="artha-price-retention-", dir="/private/tmp") as directory:
            database = Database(Path(directory) / "prices.sqlite3")
            now = datetime.now(timezone.utc).replace(microsecond=0)
            stale_at = (now - timedelta(days=2)).isoformat(timespec="seconds")
            with database._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO price_observations
                    (product_key, product_id, source_url, seller, price, currency, source_status, observed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("stale", "stale", "https://store.example/stale", "Store", 100, "INR", "direct_page", stale_at),
                )

            def offer(product_key: str, product_id: str, minutes_ago: int, price: int) -> dict[str, object]:
                return {
                    "product_key": product_key,
                    "product_id": product_id,
                    "source_url": f"https://store.example/{product_id}",
                    "seller": "Store",
                    "price": price,
                    "currency": "INR",
                    "source_status": "direct_page",
                    "observed_at": (now - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds"),
                }

            with (
                patch.object(db_module, "_PRICE_OBSERVATION_RETENTION_DAYS", 1),
                patch.object(db_module, "_MAX_PRICE_OBSERVATION_ROWS", 10),
                patch.object(db_module, "_MAX_PRICE_OBSERVATIONS_PER_PRODUCT", 2),
            ):
                database.record_price_observations([
                    offer("popular", "old", 3, 100),
                    offer("popular", "middle", 2, 90),
                    offer("popular", "new", 1, 80),
                    offer("another", "other", 0, 70),
                    offer("x" * 2100, "too-long", 0, 50),
                ])
                with database._connect() as connection:
                    rows = connection.execute("SELECT product_key, product_id FROM price_observations").fetchall()
                self.assertEqual({(row["product_key"], row["product_id"]) for row in rows}, {
                    ("popular", "middle"), ("popular", "new"), ("another", "other"),
                })
                self.assertEqual([row["price"] for row in database.price_observations("popular")], [90, 80])
                self.assertEqual(database.price_observations("stale"), [])

                with patch.object(db_module, "_MAX_PRICE_OBSERVATION_ROWS", 2):
                    database.record_price_observations([
                        offer("fresh-a", "a", 0, 60),
                        offer("fresh-b", "b", 0, 50),
                    ])
                with database._connect() as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0], 2)
                self.assertEqual(database.price_observations("fresh-a")[0]["price"], 60)
                self.assertEqual(database.price_observations("fresh-b")[0]["price"], 50)

    def test_usage_event_ledger_is_expiring_and_bounded(self) -> None:
        from datetime import datetime, timedelta, timezone

        from backend import db as db_module
        from backend.db import Database

        with tempfile.TemporaryDirectory(prefix="artha-usage-retention-", dir="/private/tmp") as directory:
            database = Database(Path(directory) / "usage.sqlite3")
            now = datetime.now(timezone.utc).replace(microsecond=0)
            with database._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO usage_events
                    (id, runtime, provider, operation, model, input_tokens, output_tokens, total_tokens,
                     cached_tokens, input_characters, output_bytes, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("usage-stale", "local", "provider", "search", None, None, None, None, None, 0, None,
                     "success", (now - timedelta(days=2)).isoformat(timespec="seconds")),
                )

            def event(event_id: str, minutes_ago: int) -> dict[str, object]:
                return {
                    "id": event_id,
                    "runtime": "local",
                    "provider": "provider",
                    "operation": "search",
                    "model": "search",
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                    "cached_tokens": None,
                    "input_characters": 10,
                    "output_bytes": None,
                    "status": "success",
                    "created_at": (now - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds"),
                }

            with (
                patch.object(db_module, "_USAGE_EVENT_RETENTION_DAYS", 1),
                patch.object(db_module, "_MAX_USAGE_EVENT_ROWS", 2),
            ):
                for item in (event("usage-a", 3), event("usage-b", 2), event("usage-c", 1)):
                    database.record_usage_event(item)
                with database._connect() as connection:
                    rows = connection.execute("SELECT id FROM usage_events ORDER BY created_at, id").fetchall()
                self.assertEqual([row["id"] for row in rows], ["usage-b", "usage-c"])

    def test_total_header_deadline_and_connection_cap(self) -> None:
        from backend import server

        started = threading.Event()

        class TrackedHandler(server.Handler):
            def setup(self) -> None:
                super().setup()
                started.set()

        with (
            patch.object(server, "_HEADER_READ_TIMEOUT_SECONDS", 0.15),
            patch.object(server, "_SOCKET_IDLE_TIMEOUT_SECONDS", 1),
            patch.object(server, "_MAX_ACTIVE_CONNECTIONS", 1),
        ):
            httpd = server.BoundedThreadingHTTPServer(("127.0.0.1", 0), TrackedHandler)
            server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            server_thread.start()
            first = second = third = None
            try:
                first = socket.create_connection(httpd.server_address, timeout=1)
                self.assertTrue(started.wait(1))
                first.settimeout(1)
                first.sendall(b"GET /missing HTTP/1.1\r\nHost: localhost\r\nX-Slow: ")
                stop_dripping = threading.Event()

                def drip_header_bytes() -> None:
                    while not stop_dripping.is_set():
                        try:
                            first.sendall(b"x")
                        except OSError:
                            return
                        time.sleep(0.03)

                dripper = threading.Thread(target=drip_header_bytes, daemon=True)
                dripper.start()
                second = socket.create_connection(httpd.server_address, timeout=1)
                second.settimeout(1)
                self.assertEqual(second.recv(1), b"")

                started_at = time.monotonic()
                while first.recv(1024):
                    pass
                self.assertLess(time.monotonic() - started_at, 0.8)

                third = socket.create_connection(httpd.server_address, timeout=1)
                third.settimeout(1)
                third.sendall(b"GET /missing HTTP/1.0\r\nHost: localhost\r\n\r\n")
                response = third.recv(1024)
                self.assertIn(b"404", response)
            finally:
                if "stop_dripping" in locals():
                    stop_dripping.set()
                    dripper.join(timeout=1)
                for connection in (first, second, third):
                    if connection is not None:
                        connection.close()
                httpd.shutdown()
                httpd.server_close()
                server_thread.join(timeout=1)

    def test_async_job_capacity_rejects_excess_work(self) -> None:
        from backend import jobs

        original_capacity = jobs._capacity
        capacity = threading.BoundedSemaphore(1)
        started = threading.Event()
        release = threading.Event()
        jobs._capacity = capacity

        def slow_search(payload, progress=None):
            started.set()
            release.wait(2)
            return {"workflow": [], "products": []}

        try:
            with patch.object(jobs, "run_search", side_effect=slow_search):
                queued = jobs.submit_search({"text": "test", "user_id": "owner"})
                self.assertIsNone(jobs.get_search_job(queued["job_id"], "different-user"))
                self.assertIsNotNone(jobs.get_search_job(queued["job_id"], "owner"))
                self.assertTrue(started.wait(1))
                with self.assertRaises(RuntimeError):
                    jobs.submit_search({"text": "overflow"})
                release.set()
                self.assertTrue(capacity.acquire(timeout=2))
                capacity.release()
                self.assertEqual(jobs.get_search_job(queued["job_id"])["status"], "complete")
        finally:
            release.set()
            if not capacity.acquire(timeout=2):
                self.fail("async job did not release its capacity slot")
            capacity.release()
            jobs._capacity = original_capacity


if __name__ == "__main__":
    unittest.main()
