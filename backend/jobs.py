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
_jobs: dict[str, dict[str, Any]] = {}
_RETENTION_SECONDS = 60 * 60


def _cleanup_locked() -> None:
    cutoff = time.time() - _RETENTION_SECONDS
    expired = [job_id for job_id, job in _jobs.items() if float(job.get("updated_at", 0)) < cutoff]
    for job_id in expired:
        _jobs.pop(job_id, None)


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

    progress(initial_workflow())
    try:
        result = run_search(payload, progress=progress)
    except Exception as error:
        with _lock:
            job = _jobs.get(job_id)
            if job:
                job["status"] = "failed"
                job["error"] = str(error)
                job["updated_at"] = time.time()
        return
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job["status"] = "complete"
            job["workflow"] = copy.deepcopy(result.get("workflow") or [])
            job["result"] = result
            job["updated_at"] = time.time()


def submit_search(payload: dict[str, Any]) -> dict[str, Any]:
    job_id = f"job-{uuid.uuid4().hex}"
    with _lock:
        _cleanup_locked()
        _jobs[job_id] = {
            "status": "queued",
            "workflow": initial_workflow(),
            "created_at": time.time(),
            "updated_at": time.time(),
        }
    _executor.submit(_run, job_id, copy.deepcopy(payload))
    with _lock:
        return _snapshot_locked(job_id) or {"job_id": job_id, "status": "queued", "workflow": initial_workflow()}


def get_search_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        _cleanup_locked()
        return _snapshot_locked(job_id)
