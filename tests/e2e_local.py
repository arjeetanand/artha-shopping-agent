"""Local end-to-end smoke test for the Artha purchase-agent flow.

This test deliberately uses the local fixture catalog and a temporary SQLite
database. It never sends the brief to Anakin, creates a real payment, or
touches the developer database.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(port: int, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, cookie: str = "") -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def wait_for_health(port: int, process: subprocess.Popen[str]) -> None:
    deadline = time.time() + 8
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("backend exited before health check")
        try:
            status, body = request(port, "/api/health")
            if status == 200 and body.get("ok") is True:
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(0.1)
    raise TimeoutError("backend did not become healthy")


def main() -> None:
    port = free_port()
    db_file = Path(tempfile.mktemp(prefix="artha-e2e-", suffix=".sqlite3", dir="/private/tmp"))
    env = os.environ.copy()
    env.update(
        {
            "SHOPPINGHELP_HOST": "127.0.0.1",
            "SHOPPINGHELP_PORT": str(port),
            "SHOPPINGHELP_DB_PATH": str(db_file),
            "SHOPPINGHELP_SEARCH_MODE": "fixture",
            "PAYMENT_PROVIDER": "sandbox",
        }
    )
    process = subprocess.Popen(
        [sys.executable, "backend/server.py"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_health(port, process)
        status, health = request(port, "/api/health")
        assert status == 200 and health["payment_provider"] == "sandbox" and health["payment_configured"] is True
        status, search = request(
            port,
            "/api/agent/search",
            method="POST",
            payload={
                "text": "I need an office chair under ₹12,000 with good back support delivered to Bangalore within 5 days",
                "location_coordinates": {"latitude": 12.9716, "longitude": 77.5946},
            },
        )
        assert status == 200, search
        assert search["intent"]["location"] == "Bengaluru"
        assert search["intent"]["location_source"].startswith("browser_permission")
        assert "location_coordinates" not in search["intent"]
        assert search["intent"]["quantity"] == 1
        assert len(search["workflow"]) == 7
        assert search["workflow"][1]["agent"] == "Location agent"
        assert search["workflow"][4]["agent"] == "Research agent"
        assert search["products"][0]["research_status"] == "complete"
        assert search["products"][0]["research_sources"][0]["status"] == "catalog"
        assert search["products"][0]["eligible"] is True
        assert search["products"][0]["line_total"] == 10490
        assert any(product["delivery_fit"] is False for product in search["products"])
        assert search["summary"]["opportunity"]["extra"] == 189

        status, queued = request(
            port,
            "/api/agent/search/jobs",
            method="POST",
            payload={"text": "Office chair under ₹12,000 delivered to Bangalore within 5 days"},
        )
        assert status == 202 and queued["status"] in {"queued", "running", "complete"}, queued
        job = queued
        for _ in range(40):
            if job["status"] in {"complete", "failed"}:
                break
            time.sleep(0.05)
            status, job = request(port, f"/api/agent/search/jobs/{queued['job_id']}")
            assert status == 200, job
        assert job["status"] == "complete", job
        assert job["result"]["products"][0]["id"] == search["products"][0]["id"]
        assert any(stage["agent"] == "Research agent" for stage in job["workflow"])

        status, refined = request(
            port,
            "/api/agent/refine",
            method="POST",
            payload={
                "text": "Actually show me options under ₹16,000 with reclining support",
                "intent": search["intent"],
                "products": search["products"],
                "source": search["source"],
            },
        )
        assert status == 200, refined
        assert refined["source"]["refined"] is True
        assert refined["intent"]["budget"] == 16000
        assert "reclining" in refined["intent"]["must_have"]
        assert refined["workflow"][0]["agent"] == "Follow-up agent"

        # Seed a real server-side session without invoking Google during local QA.
        os.environ.update(env)
        from backend.db import Database

        database = Database(db_file)
        user = database.upsert_google_user(
            google_sub="local-e2e-sub",
            email="local-e2e@example.test",
            name="Local E2E",
            picture="",
        )
        token = database.create_session(user["id"])
        cookie = f"artha_session={token}"
        selected = search["products"][0]
        status, order_response = request(
            port,
            "/api/orders",
            method="POST",
            cookie=cookie,
            payload={
                "confirmed": True,
                "search_id": search["search_id"],
                # Deliberately tampered client values: the API must use its saved search result.
                "products": [{"id": selected["id"], "price": 1, "quantity": 99, "line_total": 1}],
                "location": "Bengaluru",
            },
        )
        assert status == 201, order_response
        order = order_response["order"]
        assert order["total"] == 10490
        assert order["items"][0]["quantity"] == 1

        for expected in ("preparing", "shipped", "out_for_delivery", "delivered"):
            status, body = request(port, f"/api/orders/{order['id']}/advance", method="POST", cookie=cookie, payload={})
            assert status == 200 and body["order"]["status"] == expected, body
        status, body = request(port, f"/api/orders/{order['id']}/return", method="POST", cookie=cookie, payload={})
        assert status == 200 and body["order"]["status"] == "return_requested", body
        status, body = request(port, f"/api/orders/{order['id']}/refund", method="POST", cookie=cookie, payload={})
        assert status == 200 and body["order"]["status"] == "refunded", body

        status, body = request(port, "/api/orders", cookie=cookie)
        assert status == 200 and body["orders"][0]["status"] == "refunded", body
        print("local_e2e_ok", json.dumps({"search_id": search["search_id"], "order_id": order["id"], "workflow_steps": len(search["workflow"])}))
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        for suffix in ("", "-wal", "-shm"):
            try:
                db_file.with_name(db_file.name + suffix).unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    main()
