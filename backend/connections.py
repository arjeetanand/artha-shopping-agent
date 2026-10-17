"""Local retailer login sessions, six-month history jobs, and private invoices."""
from __future__ import annotations

import atexit
import calendar
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .db import db, now_iso
from .profile import ingest_retailer_orders, refresh_profile
from .settings import is_production, setting
from .service_logger import append_service_log
from .taste_memory import remember_orders


PROVIDERS = {"amazon", "flipkart", "myntra", "ajio", "instagram"}
_lock = threading.RLock()
_jobs: dict[tuple[str, str], dict[str, Any]] = {}
_WORKER = Path(__file__).with_name("retailer_browser.mjs")


def private_root() -> Path:
    default = Path.home() / ("Library/Application Support/Artha" if sys.platform == "darwin" else ".local/share/artha")
    return Path(setting("SHOPPINGHELP_PRIVATE_DIR", str(default))).expanduser().resolve()


def provider_directory(user_id: str, provider: str) -> Path:
    if provider not in PROVIDERS:
        raise ValueError("Unsupported retailer")
    return private_root() / hashlib.sha256(user_id.encode()).hexdigest() / provider


def six_month_cutoff(today: date | None = None) -> date:
    today = today or datetime.now(timezone(timedelta(hours=5,minutes=30))).date()
    year, month = divmod(today.year * 12 + today.month - 1 - 6, 12)
    month += 1
    return date(year,month,min(today.day,calendar.monthrange(year,month)[1]))


def _snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return {key:value for key,value in job.items() if key not in {"process", "user_id"}}


def _log(job: dict[str, Any], step: str, status: str, details: dict[str, Any] | None = None) -> None:
    try:
        append_service_log(Path(job["log_file"]), service=job["provider"], run_id=job["id"],
                           step=step, status=status, details=details)
    except OSError as error:
        job["log_error"] = type(error).__name__


def _persist(job: dict[str, Any]) -> None:
    db.save_account_connection(job["user_id"],job["provider"],"",job.get("orders",0),job["status"],details=_snapshot(job))


def start_sync(user_id: str, provider: str) -> dict[str, Any]:
    provider = str(provider).lower().strip()
    if provider not in PROVIDERS:
        raise ValueError("Choose Amazon, Flipkart, Myntra, Ajio, or Instagram")
    if is_production():
        raise RuntimeError("Retailer login runs in the local desktop app. A hosted deployment requires a separate local connector.")
    with _lock:
        key = (user_id,provider)
        existing = _jobs.get(key)
        if existing and existing["status"] in {"connecting","awaiting_login","syncing","indexing"}:
            return _snapshot(existing)
        if sum(job["status"] in {"connecting","awaiting_login","syncing","indexing"} for job in _jobs.values()) >= 2:
            raise RuntimeError("Two account connections are already running. Finish or cancel one first.")
        job = {"id":"sync-"+uuid.uuid4().hex,"user_id":user_id,"provider":provider,"status":"connecting",
               "message":"Opening a private Chrome window for retailer sign-in.","orders":0,"invoices":0,
               "cutoff":six_month_cutoff().isoformat(),"started_at":now_iso(),"coverage_complete":False}
        job["log_file"] = str(provider_directory(user_id,provider)/"logger.txt")
        job["until"] = datetime.now(timezone(timedelta(hours=5,minutes=30))).date().isoformat()
        _jobs[key] = job
        _persist(job)
        threading.Thread(target=_run,args=(job,),daemon=True,name=f"retailer-{provider}").start()
        return _snapshot(job)


def _store_invoice(user_id: str, provider: str, event: dict[str, Any], directory: Path) -> None:
    filename = str(event.get("filename") or "")
    if not re.fullmatch(r"[a-f0-9]{64}\.pdf",filename):
        raise ValueError("Invalid invoice filename")
    file = directory / "invoices" / filename
    content = file.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if len(content)>20*1024*1024 or not content.startswith(b"%PDF-") or digest != event.get("sha256"):
        raise ValueError("Retailer invoice did not pass file validation")
    file.chmod(0o600)
    from pypdf import PdfReader
    reader = PdfReader(file)
    text = ""
    if not reader.is_encrypted:
        text = "\n".join(page.extract_text() or "" for page in reader.pages[:100])[:200000]
    text_file = file.with_suffix(".txt")
    text_file.write_text(text,encoding="utf-8")
    text_file.chmod(0o600)
    db.save_retailer_invoice(user_id,provider,str(event["retailer_order_id"]),str(file.relative_to(private_root())),digest)


def _run(job: dict[str, Any]) -> None:
    directory = provider_directory(job["user_id"],job["provider"])
    records = []
    process = None
    timer = None
    try:
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        directory.chmod(0o700)
        for parent in (private_root(),directory.parent):
            parent.chmod(0o700)
        _log(job,"sync_started","info",{"cutoff":job["cutoff"],"until":job["until"]})
        process = subprocess.Popen(["node",str(_WORKER)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL,text=True,encoding="utf-8")
        _log(job,"worker_started","info")
        with _lock:
            job["process"] = process
        timer = threading.Timer(30*60,process.terminate)
        timer.daemon=True
        timer.start()
        payload = {"provider":job["provider"],"cutoff":job["cutoff"],"until":job["until"],"profile_dir":str(directory/"browser"),"invoice_dir":str(directory/"invoices")}
        process.stdin.write(json.dumps(payload)); process.stdin.close()
        final = None
        for line in process.stdout:
            if len(line)>2_000_000:
                raise ValueError("Retailer returned an oversized event")
            event = json.loads(line)
            with _lock:
                if job["status"] == "cancelled":
                    break
            if event.get("type") == "order":
                records.extend(ingest_retailer_orders(job["user_id"],job["provider"],[event["order"]],date.fromisoformat(job["cutoff"])))
                _log(job,"order_ingested","info",{"order_count":len(records)})
            elif event.get("type") == "invoice":
                try:
                    _store_invoice(job["user_id"],job["provider"],event,directory)
                    _log(job,"invoice_saved","info",{"invoice_count":1})
                except Exception as error:
                    job["invoice_read_errors"] = job.get("invoice_read_errors",0)+1
                    _log(job,"invoice_save_failed","warn",{"error_class":type(error).__name__})
            elif event.get("type") == "log":
                details = event.get("details") if isinstance(event.get("details"),dict) else {}
                _log(job,str(event.get("step") or "worker_event"),str(event.get("status") or "info"),details)
            elif event.get("type") == "progress":
                progress_details = {"page":event.get("pages"),"order_count":event.get("orders"),"invoice_count":event.get("invoices")}
                _log(job,"worker_progress",str(event.get("status") or "running"),progress_details)
                with _lock:
                    job.update({key:event[key] for key in ("status","message","orders","invoices","pages") if key in event})
                    _persist(job)
            elif event.get("type") == "complete":
                final = {key:value for key,value in event.items() if key != "type"}
            elif event.get("type") == "error":
                raise RuntimeError(str(event.get("message") or "Retailer sync failed"))
        process.wait(timeout=10)
        with _lock:
            if job["status"] == "cancelled":
                return
        if not final or process.returncode:
            raise RuntimeError("Retailer connection stopped before confirming history coverage. Reconnect to continue.")
        _log(job,"history_complete","info",{
            "order_count":final.get("orders"),"invoice_count":final.get("invoices"),
            **{key:final[key] for key in ("missing_invoices","missing_dates","unreadable_pages","pages",
                                           "coverage_complete","window_limited","cutoff") if key in final},
        })
        with _lock:
            job.update({"status":"indexing","message":"Building your taste memory from verified purchase items."})
            _persist(job)
        remember_orders(job["user_id"],records)
        _log(job,"taste_memory_updated","info",{"order_count":len(records)})
        with _lock:
            if job["status"] == "cancelled":
                return
            job.update(final)
            if job["provider"] != "instagram" and (not final.get("coverage_complete") or final.get("missing_invoices") or job.get("invoice_read_errors")):
                job["status"] = "partial"
            job["finished_at"] = now_iso()
            job["message"] = "Account connected." if job["provider"] == "instagram" else "Sync finished. Check order and invoice coverage below."
            _persist(job)
        refresh_profile(job["user_id"])
    except Exception as error:
        _log(job,"sync_failed","error",{"error_class":type(error).__name__})
        if process and process.poll() is None:
            process.terminate()
        if records:
            remember_orders(job["user_id"],records)
        with _lock:
            if job["status"] != "cancelled":
                message = "The app cannot access private browser storage. Restart it from your normal terminal with ./run.sh, then reconnect." if isinstance(error,PermissionError) else str(error)[:400]
                job.update({"status":"failed","message":message,"orders":len(records),"coverage_complete":False,"finished_at":now_iso()})
                _persist(job)
        refresh_profile(job["user_id"])
    finally:
        if timer:
            timer.cancel()
        if process and process.poll() is None:
            process.terminate()
        with _lock:
            job.pop("process",None)


def list_connections(user_id: str) -> list[dict[str, Any]]:
    records = db.list_account_connections(user_id)
    with _lock:
        for record in records:
            job = _jobs.get((user_id,record["provider"]))
            if job:
                record["details"] = _snapshot(job)
                record["status"] = job["status"]
            elif record["status"] in {"connecting","awaiting_login","syncing","indexing"}:
                record["status"] = "interrupted"
                record["details"]["message"] = "The app restarted before sync finished. Reconnect to resume."
            record.pop("details_json",None)
    return records


def cancel_sync(user_id: str, provider: str) -> None:
    with _lock:
        job = _jobs.get((user_id,provider))
        if job and job["status"] in {"connecting","awaiting_login","syncing","indexing"}:
            job["status"] = "cancelled"
            if job.get("process"):
                job["process"].terminate()
            _persist(job)


def disconnect(user_id: str, provider: str) -> None:
    cancel_sync(user_id,provider)
    directory = provider_directory(user_id,provider)/"browser"
    with _lock:
        process = _jobs.get((user_id,provider),{}).get("process")
    if process:
        try: process.wait(timeout=8)
        except subprocess.TimeoutExpired: raise RuntimeError("Chrome is still closing. Try disconnecting again shortly.")
    if directory.exists():
        shutil.rmtree(directory)
    db.save_account_connection(user_id,provider,"",status="disconnected",details={"message":"Login session removed. Synced orders and invoices remain in your history."})
    with _lock:
        _jobs.pop((user_id,provider),None)


def invoice_file(user_id: str, invoice_id: str) -> Path | None:
    invoice = db.get_retailer_invoice(user_id,invoice_id)
    if not invoice:
        return None
    root = private_root()
    file = (root/invoice["relative_path"]).resolve()
    expected = provider_directory(user_id,invoice["provider"]).resolve()
    if not file.is_relative_to(expected) or not file.is_file():
        return None
    return file


def _shutdown() -> None:
    with _lock:
        processes = [job["process"] for job in _jobs.values() if job.get("process") and job["process"].poll() is None]
    for process in processes:
        process.terminate()
    for process in processes:
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()


atexit.register(_shutdown)
