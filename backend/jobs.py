"""Small in-process job queue for long-running live research.

Jobs are intentionally ephemeral: local development and a single API process
do not need another queue service, while the API contract leaves room for a
durable worker later. The browser receives progress snapshots and never has
to hold a request open while Anakin or a direct-page check is running.
"""

from __future__ import annotations

import copy
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .workflow import initial_workflow, run_search


_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="artha-research")
_lock = threading.Lock()
_capacity = threading.BoundedSemaphore(32)
_jobs: dict[str, dict[str, Any]] = {}
_search_clients: dict[str, tuple[float, int]] = {}
_RETENTION_SECONDS = 60 * 60
_MAX_RETAINED_JOBS = 128
_SEARCH_REQUESTS_PER_MINUTE = 20
_MAX_TRACKED_SEARCH_CLIENTS = 4096
_last_client_cleanup = 0.0


def _cleanup_locked() -> None:
    cutoff = time.time() - _RETENTION_SECONDS
    expired = [job_id for job_id, job in _jobs.items() if float(job.get("updated_at", 0)) < cutoff]
    for job_id in expired:
        _jobs.pop(job_id, None)


def allow_search_request(client_ip: str) -> bool:
    global _last_client_cleanup
    now = time.monotonic()
    with _lock:
        if now - _last_client_cleanup >= 60:
            _search_clients_copy = [ip for ip, (started, _) in _search_clients.items() if now - started >= 60]
            for ip in _search_clients_copy:
                _search_clients.pop(ip, None)
            _last_client_cleanup = now
        entry = _search_clients.get(client_ip)
        if entry is None or now - entry[0] >= 60:
            if entry is None and len(_search_clients) >= _MAX_TRACKED_SEARCH_CLIENTS:
                # ponytail: in-process peer-IP limits; use a shared limiter behind trusted proxy identity when scaling out.
                return False
            _search_clients[client_ip] = (now, 1)
            return True
        if entry[1] >= _SEARCH_REQUESTS_PER_MINUTE:
            return False
        _search_clients[client_ip] = (entry[0], entry[1] + 1)
        return True


def _snapshot_locked(job_id: str) -> dict[str, Any] | None:
    job = _jobs.get(job_id)
    if not job:
        return None
    snapshot = {"job_id": job_id, "status": job["status"], "workflow": copy.deepcopy(job.get("workflow") or [])}
    if job.get("result") is not None:
        snapshot["result"] = copy.deepcopy(job["result"])
    if job.get("error"):
        snapshot["error"] = str(job["error"])
    return snapshot


def _run(job_id: str, payload: dict[str, Any]) -> None:
    def progress(workflow: list[dict[str, Any]]) -> None:
        with _lock:
            job = _jobs.get(job_id)
            if not job:
                return
            job["status"] = "running"
            job["workflow"] = copy.deepcopy(workflow)
            job["updated_at"] = time.time()

    try:
        progress(initial_workflow())
        result = run_search(payload, progress=progress)
    except Exception as error:
        with _lock:
            job = _jobs.get(job_id)
            if job:
                job["status"] = "failed"
                job["error"] = str(error)
                job["updated_at"] = time.time()
    else:
        with _lock:
            job = _jobs.get(job_id)
            if job:
                job["status"] = "complete"
                job["workflow"] = copy.deepcopy(result.get("workflow") or [])
                job["result"] = result
                job["updated_at"] = time.time()
    finally:
        _capacity.release()


def submit_search(payload: dict[str, Any]) -> dict[str, Any]:
    if not _capacity.acquire(blocking=False):
        raise RuntimeError("Research queue is full; try again shortly.")
    job_id = f"job-{uuid.uuid4().hex}"
    submitted = False
    try:
        queued_payload = copy.deepcopy(payload)
        with _lock:
            _cleanup_locked()
            while len(_jobs) >= _MAX_RETAINED_JOBS:
                terminal = [
                    (float(job.get("updated_at", 0)), old_id)
                    for old_id, job in _jobs.items()
                    if job.get("status") in {"complete", "failed"}
                ]
                if not terminal:
                    raise RuntimeError("Research queue is full; try again shortly.")
                _, oldest_job_id = min(terminal)
                _jobs.pop(oldest_job_id, None)
            now = time.time()
            _jobs[job_id] = {
                "user_id": str(queued_payload.get("user_id") or "shopper-local"),
                "status": "queued",
                "workflow": initial_workflow(),
                "created_at": now,
                "updated_at": now,
            }
        _executor.submit(_run, job_id, queued_payload)
        submitted = True
        with _lock:
            return _snapshot_locked(job_id) or {"job_id": job_id, "status": "queued", "workflow": initial_workflow()}
    except Exception:
        if not submitted:
            with _lock:
                _jobs.pop(job_id, None)
            _capacity.release()
        raise


def get_search_job(job_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    with _lock:
        _cleanup_locked()
        if user_id is not None and _jobs.get(job_id, {}).get("user_id") != user_id:
            return None
        return _snapshot_locked(job_id)
