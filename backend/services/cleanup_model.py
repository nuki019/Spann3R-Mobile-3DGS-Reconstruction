"""Cleanup helpers for dashboard management actions."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, Iterable

from pipeline.job_queue import sanitize_job_id
from services.asset_inventory import list_images


def clear_uploaded_inputs(watch_dir: Path) -> int:
    deleted = 0
    for image_path in list_images(watch_dir):
        image_path.unlink(missing_ok=True)
        deleted += 1
    for part_path in watch_dir.glob("*.part") if watch_dir.exists() else []:
        part_path.unlink(missing_ok=True)
        deleted += 1
    manifest = watch_dir / "_upload_manifest.jsonl"
    if manifest.exists():
        manifest.unlink(missing_ok=True)
        deleted += 1
    return deleted


def clear_non_running_jobs(queue_root: Path, jobs: Iterable[Dict[str, object]]) -> int:
    if not queue_root.exists():
        return 0
    deleted = 0
    for job in jobs:
        status = str(job.get("status") or "")
        if status == "running":
            continue
        job_id = sanitize_job_id(str(job.get("id") or job.get("job_id") or ""))
        path = queue_root / job_id
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            deleted += 1
    return deleted
