"""Pure storage helpers for scene assets and upload cleanup."""

from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"}


def list_images(directory: Path) -> List[Path]:
    if not directory.exists():
        return []
    images = [p for p in directory.iterdir() if p.is_file() and p.suffix in IMAGE_EXTENSIONS]
    images.sort(key=lambda p: (p.stat().st_mtime_ns, p.name))
    return images


def build_image_fingerprint(images: Iterable[Path]) -> Tuple[Tuple[str, int, int], ...]:
    return tuple((path.name, path.stat().st_size, path.stat().st_mtime_ns) for path in images)


def sanitize_scene_name(raw: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in raw.strip())
    cleaned = cleaned.strip("_")
    return cleaned or "scene"


def build_scene_name(prefix: str, images: Iterable[Path], timestamp: str = "") -> str:
    safe_prefix = sanitize_scene_name(prefix)
    fingerprint = build_image_fingerprint(images)
    digest = hashlib.sha1(repr(fingerprint).encode("utf-8")).hexdigest()[:8]
    created_at = timestamp or time.strftime("%Y%m%d_%H%M%S")
    return f"{safe_prefix}_{created_at}_{digest}"


def snapshot_images(images: List[Path], target_root: Path, scene_name: str) -> Path:
    scene_photo_dir = target_root / scene_name
    if scene_photo_dir.exists():
        shutil.rmtree(scene_photo_dir)
    scene_photo_dir.mkdir(parents=True, exist_ok=True)
    for image_path in images:
        shutil.copy2(image_path, scene_photo_dir / image_path.name)
    return scene_photo_dir


def mark_latest_scene(scene_data_root: Path, scene_name: str) -> None:
    marker = scene_data_root / "LATEST_SCENE.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(scene_name + "\n", encoding="utf-8")


def prune_child_dirs(root: Path, keep: int, protected_name: str = "") -> int:
    if keep <= 0 or not root.exists():
        return 0
    candidates = [item for item in root.iterdir() if item.is_dir() and item.name != protected_name]
    candidates.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)
    deleted = 0
    for old_dir in candidates[max(keep - 1, 0):]:
        shutil.rmtree(old_dir, ignore_errors=True)
        deleted += 1
    return deleted


def cleanup_upload_inputs(
    watch_dir: Path,
    archive_dir: Path,
    archive_input: bool,
    clear_input_after_snapshot: bool,
    timestamp: str = "",
) -> Dict[str, object]:
    images = list_images(watch_dir)
    part_files = sorted(watch_dir.glob("*.part")) if watch_dir.exists() else []
    manifest_file = watch_dir / "_upload_manifest.jsonl"
    if not images and not part_files and not manifest_file.exists():
        return {"mode": "empty", "deleted": 0, "archived": 0, "archive_dir": ""}

    if not archive_input:
        if not clear_input_after_snapshot:
            return {"mode": "keep", "deleted": 0, "archived": 0, "archive_dir": ""}
        deleted = 0
        for image_path in images:
            image_path.unlink(missing_ok=True)
            deleted += 1
        for part_path in part_files:
            part_path.unlink(missing_ok=True)
        manifest_file.unlink(missing_ok=True)
        return {"mode": "delete", "deleted": deleted, "archived": 0, "archive_dir": ""}

    archive_subdir = archive_dir / (timestamp or time.strftime("%Y%m%d_%H%M%S"))
    archive_subdir.mkdir(parents=True, exist_ok=True)
    for image_path in images:
        shutil.move(str(image_path), archive_subdir / image_path.name)
    if manifest_file.exists():
        shutil.move(str(manifest_file), archive_subdir / manifest_file.name)
    for part_path in part_files:
        shutil.move(str(part_path), archive_subdir / part_path.name)
    return {"mode": "archive", "deleted": 0, "archived": len(images), "archive_dir": str(archive_subdir)}
