"""Process one sanitized browser-extension batch for an authenticated retailer."""
from __future__ import annotations

import json
import subprocess
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .connections import six_month_cutoff
from .db import db, now_iso
from .profile import ingest_retailer_orders, refresh_profile
from .taste_memory import remember_orders

PROVIDERS = {"amazon", "flipkart", "myntra", "ajio"}
DOMAINS = {"amazon": "amazon.in", "flipkart": "flipkart.com", "myntra": "myntra.com", "ajio": "ajio.com"}
HISTORY_PATHS = {"amazon": "/gp/your-account/order-history", "myntra": "/my/orders", "ajio": "/my-account/orders"}
MAX_PAGES = 100
MAX_BATCH_BYTES = 7_500_000
_PARSER = Path(__file__).with_name("retailer_parse_pages.mjs")
_lock = threading.RLock()
_jobs: dict[tuple[str, str], dict[str, Any]] = {}
_ACTIVE = {"connecting", "awaiting_login", "syncing", "indexing"}


def _snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key not in {"user_id", "page_payloads", "cancellable"}}


def _persist(job: dict[str, Any]) -> dict[str, Any]:
    return db.save_account_connection(
        job["user_id"], job["provider"], "", job.get("orders", 0), job["status"], details=_snapshot(job)
    )


def _existing(user_id: str, provider: str) -> dict[str, Any] | None:
    return next((row for row in db.list_account_connections(user_id) if row["provider"] == provider), None)


def _trusted_history_url(value: Any, provider: str) -> bool:
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        domain = DOMAINS[provider]
        history_path = HISTORY_PATHS[provider]
        path = url.path.rstrip("/")
        return (url.scheme == "https" and not url.username and not url.password and not url.port
                and (host == domain or host.endswith("." + domain))
                and (path == history_path or path.startswith(history_path + "/")))
    except (TypeError, ValueError):
        return False


def _run(job: dict[str, Any]) -> None:
    try:
        raw = json.dumps({"provider": job["provider"], "pages": job["page_payloads"]}, separators=(",", ":"))
        result = subprocess.run(["node", str(_PARSER)], input=raw, text=True, capture_output=True, timeout=30, check=True)
        parsed_pages = json.loads(result.stdout)
        if not isinstance(parsed_pages, list) or len(parsed_pages) != len(job["page_payloads"]):
            raise ValueError("Retailer parser returned an invalid result")

        cutoff = six_month_cutoff()
        until = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        orders: dict[str, dict[str, Any]] = {}
        unreadable = 0
        cutoff_reached = False
        for page in parsed_pages:
            if not isinstance(page, dict) or page.get("error"):
                unreadable += 1
                continue
            unreadable += len(page.get("errors", []))
            for order in page.get("orders", []):
                order_date = date.fromisoformat(order["order_date"])
                cutoff_reached |= order_date < cutoff
                if cutoff <= order_date <= until:
                    orders.setdefault(order["id"], order)
        if len(orders) > 5000:
            raise ValueError("Retailer returned too many orders")

        with _lock:
            if job["status"] not in _ACTIVE:
                return
            job.update({"status": "indexing", "message": "Saving verified orders and building your taste memory."})
            _persist(job)
            job["cancellable"] = False
            records = ingest_retailer_orders(job["user_id"], job["provider"], list(orders.values()), cutoff)
        memory_ready = True
        try:
            remember_orders(job["user_id"], records)
            refresh_profile(job["user_id"])
        except Exception:
            memory_ready = False

        history_checked = job["stop_reason"] == "history_end" or (job["stop_reason"] == "six_month_window" and cutoff_reached)
        coverage_complete = history_checked and unreadable == 0
        status = "synced" if coverage_complete and memory_ready else "partial"
        retailer = job["provider"].title()
        message = f"Imported {len(records)} orders from {retailer} for the last six months. Invoice PDFs aren't included in the portal connector."
        if not coverage_complete:
            message += f" {retailer} did not confirm complete history coverage."
        elif not memory_ready:
            message += " Taste memory needs a retry."
        with _lock:
            if job["status"] not in _ACTIVE:
                return
            job.update({
                "status": status, "message": message, "orders": len(records), "invoices": 0,
                "invoice_support": False, "pages": len(parsed_pages), "cutoff": cutoff.isoformat(),
                "coverage_complete": coverage_complete, "unreadable_orders": unreadable,
                "finished_at": now_iso(),
            })
            _persist(job)
        try:
            refresh_profile(job["user_id"])
        except Exception:
            pass
    except Exception:
        with _lock:
            if job["status"] in _ACTIVE:
                job.update({"status": "failed", "message": f"{job['provider'].title()} history could not be processed. Connect again to retry.", "finished_at": now_iso()})
                _persist(job)
    finally:
        with _lock:
            _jobs.pop((job["user_id"], job["provider"]), None)
            job.pop("page_payloads", None)


def submit_batch(user_id: str, provider: Any, pages: Any, stop_reason: Any) -> dict[str, Any]:
    provider = str(provider or "").lower().strip()
    if provider not in PROVIDERS:
        raise ValueError("Choose Amazon, Flipkart, Myntra, or Ajio")
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        raise ValueError("The retailer sync must include between 1 and 100 history pages")
    if stop_reason not in {"history_end", "six_month_window", "page_limit"}:
        raise ValueError("Invalid retailer history completion reason")
    if len(json.dumps({"pages": pages, "stop_reason": stop_reason}, separators=(",", ":")).encode("utf-8")) > MAX_BATCH_BYTES:
        raise ValueError("Retailer history batch is too large; sync a smaller history window")
    if provider != "flipkart" and sum(len(page.get("orders", [])) for page in pages if isinstance(page, dict)) > 5000:
        raise ValueError("Retailer returned too many order records")
    for page in pages:
        if provider == "flipkart":
            view = page.get("RESPONSE", {}).get("multipleOrderDetailsView") if isinstance(page, dict) else None
            valid = isinstance(view, dict) and isinstance(view.get("orders"), list)
        else:
            valid = isinstance(page, dict) and _trusted_history_url(page.get("url"), provider) and isinstance(page.get("orders"), list)
            valid = valid and all(isinstance(order, dict) and _trusted_history_url(order.get("url"), provider) for order in page["orders"])
        if not valid:
            raise ValueError(f"{provider.title()} returned an unreadable order-history page")

    with _lock:
        current = _existing(user_id, provider)
        if current and current["status"] in _ACTIVE:
            raise RuntimeError(f"A {provider.title()} history sync is already running")
        job = {
            "id": provider + "-" + uuid.uuid4().hex, "user_id": user_id, "provider": provider,
            "connector": "chrome_extension", "status": "indexing",
            "message": f"Processing {len(pages)} {provider.title()} history pages.", "page_payloads": pages,
            "pages": len(pages), "cancellable": True,
            "orders": 0, "invoices": 0, "invoice_support": False, "coverage_complete": False,
            "stop_reason": stop_reason, "started_at": now_iso(), "cutoff": six_month_cutoff().isoformat(),
        }
        _jobs[(user_id, provider)] = job
        connection = _persist(job)
        threading.Thread(target=_run, args=(job,), daemon=True, name=f"{provider}-extension-sync").start()
        return connection


def cancel(user_id: str, provider: Any) -> None:
    provider = str(provider or "").lower().strip()
    if provider not in PROVIDERS:
        raise ValueError("Unsupported retailer")
    with _lock:
        job = _jobs.get((user_id, provider))
        current = _existing(user_id, provider)
        if not current or current["status"] not in _ACTIVE:
            return
        if job:
            if not job.get("cancellable", True):
                raise RuntimeError(f"{provider.title()} orders are being saved and can no longer be cancelled")
            job["status"] = "cancelled"
            job["message"] = f"{provider.title()} history sync cancelled."
            job.pop("page_payloads", None)
            _persist(job)
        else:
            db.save_account_connection(user_id, provider, "", current["synced_orders_count"], "cancelled",
                                       details={"connector": "chrome_extension", "message": f"{provider.title()} history sync cancelled."})


def disconnect(user_id: str, provider: Any) -> None:
    provider = str(provider or "").lower().strip()
    cancel(user_id, provider)
    db.save_account_connection(user_id, provider, "", status="disconnected",
                               details={"connector": "chrome_extension", "message": "Portal connector disconnected. Synced orders remain in your history."})
