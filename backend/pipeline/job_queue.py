import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from pipeline.job_policy import (
    is_runnable_job_status,
    next_status_after_upload,
    summarize_job_statuses,
)


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"}


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def sanitize_job_id(raw: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", (raw or "").strip())
    value = value.strip("._-")
    return value[:80] or f"job_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"


def job_dir(queue_root: Path, job_id: str) -> Path:
    return queue_root / sanitize_job_id(job_id)


def job_images_dir(queue_root: Path, job_id: str) -> Path:
    return job_dir(queue_root, job_id) / "images"


def job_status_path(queue_root: Path, job_id: str) -> Path:
    return job_dir(queue_root, job_id) / "status.json"


def list_images(directory: Path) -> List[Path]:
    if not directory.exists():
        return []
    images = [item for item in directory.iterdir() if item.is_file() and item.suffix in IMAGE_EXTENSIONS]
    images.sort(key=lambda path: (path.stat().st_mtime_ns, path.name))
    return images


def build_image_fingerprint(images: Iterable[Path]) -> Tuple[Tuple[str, int, int], ...]:
    return tuple((path.name, path.stat().st_size, path.stat().st_mtime_ns) for path in images)


def read_job(queue_root: Path, job_id: str) -> Dict[str, object]:
    path = job_status_path(queue_root, job_id)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_job(queue_root: Path, job: Dict[str, object]) -> Dict[str, object]:
    job_id = sanitize_job_id(str(job.get("id") or job.get("job_id") or ""))
    if not job_id:
        raise ValueError("job id is required")

    current = read_job(queue_root, job_id)
    payload = dict(current)
    payload.update(job)
    payload["id"] = job_id
    payload["job_id"] = job_id
    payload["updated_at"] = utc_now()
    payload.setdefault("created_at", payload["updated_at"])
    payload.setdefault("status", "queued")
    payload.setdefault("scene_name", "")
    payload.setdefault("error", "")
    payload.setdefault("message", "")

    directory = job_dir(queue_root, job_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = job_status_path(queue_root, job_id)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return payload


def record_uploaded_frame(
    queue_root: Path,
    job_id: str,
    filename: str,
    size_bytes: int,
    frame_index: str = "",
    source_name: str = "",
) -> Dict[str, object]:
    safe_id = sanitize_job_id(job_id)
    images = list_images(job_images_dir(queue_root, safe_id))
    current = read_job(queue_root, safe_id)
    current_status = str(current.get("status") or "")
    next_status = next_status_after_upload(current_status)
    manifest_path = job_dir(queue_root, safe_id) / "upload_manifest.jsonl"
    manifest_row = {
        "filename": filename,
        "bytes": size_bytes,
        "frame_index": frame_index,
        "source_name": source_name,
        "created_at": utc_now(),
    }
    with manifest_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest_row, ensure_ascii=False) + "\n")

    return write_job(
        queue_root,
        {
            "id": safe_id,
            "status": next_status,
            "message": "等待训练队列消费" if next_status == "queued" else str(current.get("message") or ""),
            "image_count": len(images),
            "input_dir": str(job_images_dir(queue_root, safe_id)),
            "manifest": str(manifest_path),
        },
    )


def list_jobs(queue_root: Path, limit: int = 200) -> List[Dict[str, object]]:
    if not queue_root.exists():
        return []
    jobs: List[Dict[str, object]] = []
    for child in queue_root.iterdir():
        if not child.is_dir():
            continue
        payload = read_job(queue_root, child.name)
        if not payload:
            continue
        payload["image_count"] = len(list_images(child / "images"))
        payload["input_dir"] = str(child / "images")
        jobs.append(payload)
    jobs.sort(key=lambda item: str(item.get("created_at") or item.get("updated_at") or ""))
    return jobs[:limit]


def list_runnable_jobs(queue_root: Path) -> List[Dict[str, object]]:
    return [job for job in list_jobs(queue_root) if is_runnable_job_status(job.get("status"))]


def mark_job(
    queue_root: Path,
    job_id: str,
    status: str,
    message: str = "",
    scene_name: str = "",
    error: str = "",
    extra: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "id": sanitize_job_id(job_id),
        "status": status,
        "message": message,
        "error": error,
    }
    if scene_name:
        payload["scene_name"] = scene_name
    if status in {"completed", "failed", "stopped"}:
        payload["completed_at"] = utc_now()
    if extra:
        payload.update(extra)
    return write_job(queue_root, payload)


def summarize_jobs(queue_root: Path) -> Dict[str, object]:
    return summarize_job_statuses(list_jobs(queue_root))
