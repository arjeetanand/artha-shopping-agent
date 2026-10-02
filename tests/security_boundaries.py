"""Focused regression checks for the security scan fixes."""

from __future__ import annotations

import os
import socket
import sys
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
                queued = jobs.submit_search({"text": "test"})
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
