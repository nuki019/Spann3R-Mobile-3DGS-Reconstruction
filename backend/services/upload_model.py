"""Pure upload naming and routing helpers shared by upload endpoints."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from pipeline.job_queue import job_images_dir, sanitize_job_id
from pipeline.job_policy import can_upload_by_phase


VALID_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def validate_upload_suffix(filename: str, allowed: Iterable[str] = VALID_UPLOAD_EXTENSIONS) -> str:
    suffix = Path(filename or "").suffix.lower()
    allowed_set = {item.lower() for item in allowed}
    if suffix not in allowed_set:
        allowed_text = "/".join(sorted(item.lstrip(".") for item in allowed_set))
        raise ValueError(f"仅支持 {allowed_text} 格式")
    return suffix


def sanitize_frame_index(frame_index: str) -> str:
    return re.sub(r"[^0-9]+", "", frame_index or "")[:8]


def build_upload_filename(
    job_id: str,
    frame_index: str,
    suffix: str,
    timestamp: Optional[datetime] = None,
    nonce: Optional[str] = None,
) -> str:
    safe_job_id = sanitize_job_id(job_id or "wx")
    safe_index = sanitize_frame_index(frame_index)
    index_part = f"_{safe_index}" if safe_index else ""
    created_at = timestamp or datetime.utcnow()
    unique_part = (nonce or uuid.uuid4().hex[:8])[:16]
    return f"{created_at.strftime('%Y%m%d%H%M%S_%f')}_{safe_job_id}{index_part}_{unique_part}{suffix}"


def resolve_upload_destination(
    queue_enabled: bool,
    queue_root: Path,
    watch_dir: Path,
    session_id: str,
) -> Tuple[str, Path]:
    safe_session = sanitize_job_id(session_id or "wx")
    save_dir = job_images_dir(queue_root, safe_session) if queue_enabled else watch_dir
    return safe_session, save_dir


def build_upload_manifest_row(
    filename: str,
    size_bytes: int,
    phase: str,
    job_id: str,
    frame_index: str,
    session_id: str,
    created_at: Optional[datetime] = None,
) -> Dict[str, object]:
    timestamp = created_at or datetime.utcnow()
    return {
        "filename": filename,
        "bytes": size_bytes,
        "phase": phase,
        "job_id": job_id,
        "frame_index": frame_index,
        "session_id": session_id,
        "created_at": timestamp.isoformat() + "Z",
    }


def build_upload_response(
    filename: str,
    size_bytes: int,
    phase: str,
    job_id: str,
    queue_enabled: bool,
    job: Dict[str, object],
) -> Dict[str, object]:
    return {
        "code": 200,
        "ok": True,
        "msg": "上传成功",
        "filename": filename,
        "bytes": size_bytes,
        "phase": phase,
        "job_id": job_id,
        "queue_enabled": queue_enabled,
        "job": job,
    }


def build_upload_stats_payload(
    phase: str,
    queue_enabled: bool,
    queue_summary: Dict[str, object],
    uploaded_files: int,
    uploaded_bytes: int,
    save_dir: Path,
    legacy_save_dir: Path,
    max_file_size_mb: int,
    active_job: Optional[Dict[str, object]],
) -> Dict[str, object]:
    return {
        "status": "ok",
        "phase": phase,
        "allow_upload": queue_enabled or can_upload_by_phase(phase),
        "queue_enabled": queue_enabled,
        "queue": queue_summary if queue_enabled else {"count": 0, "queued": 0},
        "uploaded_files": uploaded_files,
        "uploaded_bytes": uploaded_bytes,
        "save_dir": str(save_dir),
        "legacy_save_dir": str(legacy_save_dir),
        "max_file_size_mb": max_file_size_mb,
        "active_job": active_job,
    }
