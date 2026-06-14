"""Shared job and phase policy helpers for the delivery pipeline."""

from __future__ import annotations

from typing import Dict, Iterable


RUNNABLE_JOB_STATUSES = {"queued", "uploading", "ready"}
LOCKED_UPLOAD_JOB_STATUSES = {"running", "completed", "failed", "stopped"}
TERMINAL_JOB_STATUSES = {"completed", "failed", "stopped"}
UPLOAD_ALLOWED_PHASES = {"idle", "input", "upload", "stopped", "unknown"}


def normalize_status(status: object) -> str:
    return str(status or "").strip().lower()


def is_runnable_job_status(status: object) -> bool:
    return normalize_status(status) in RUNNABLE_JOB_STATUSES


def can_cancel_job_status(status: object) -> bool:
    return is_runnable_job_status(status)


def is_terminal_job_status(status: object) -> bool:
    return normalize_status(status) in TERMINAL_JOB_STATUSES


def next_status_after_upload(current_status: object) -> str:
    normalized = normalize_status(current_status)
    if normalized in LOCKED_UPLOAD_JOB_STATUSES:
        return normalized
    return "queued"


def can_upload_by_phase(phase: object) -> bool:
    return normalize_status(phase) in UPLOAD_ALLOWED_PHASES


def summarize_job_statuses(jobs: Iterable[Dict[str, object]]) -> Dict[str, object]:
    job_list = list(jobs)
    counts: Dict[str, int] = {}
    for job in job_list:
        status = normalize_status(job.get("status")) or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return {
        "count": len(job_list),
        "queued": sum(counts.get(status, 0) for status in RUNNABLE_JOB_STATUSES),
        "running": counts.get("running", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "stopped": counts.get("stopped", 0),
        "by_status": counts,
    }
