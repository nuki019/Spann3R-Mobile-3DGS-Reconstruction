"""Filesystem inventory helpers for dashboard assets."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"}


def format_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def list_images(directory: Path) -> List[Path]:
    if not directory.exists():
        return []
    files = [item for item in directory.iterdir() if item.is_file() and item.suffix in IMAGE_EXTENSIONS]
    files.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)
    return files


def discover_uploaded_images(watch_dir: Path, limit: int = 200) -> List[Dict[str, str]]:
    payload: List[Dict[str, str]] = []
    for image_path in list_images(watch_dir)[:limit]:
        stat = image_path.stat()
        payload.append(
            {
                "name": image_path.name,
                "size_bytes": str(stat.st_size),
                "mtime": format_mtime(image_path),
                "path": str(image_path),
            }
        )
    return payload


def discover_archive_dirs(archive_root: Path, limit: int = 20) -> List[Dict[str, str]]:
    if not archive_root.exists():
        return []
    candidates = [item for item in archive_root.iterdir() if item.is_dir()]
    candidates.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)

    payload: List[Dict[str, str]] = []
    for archive_dir in candidates[:limit]:
        files = [item for item in archive_dir.rglob("*") if item.is_file()]
        image_count = len([item for item in files if item.suffix in IMAGE_EXTENSIONS])
        total_size = sum(item.stat().st_size for item in files)
        payload.append(
            {
                "name": archive_dir.name,
                "path": str(archive_dir),
                "image_count": str(image_count),
                "file_count": str(len(files)),
                "size_bytes": str(total_size),
                "mtime": format_mtime(archive_dir),
            }
        )
    return payload


def discover_photo_scenes(test_photo_root: Path, limit: int = 200) -> List[Dict[str, str]]:
    if not test_photo_root.exists():
        return []
    candidates = [item for item in test_photo_root.iterdir() if item.is_dir()]
    candidates.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)

    payload: List[Dict[str, str]] = []
    for scene_dir in candidates[:limit]:
        image_count = len([item for item in scene_dir.iterdir() if item.is_file() and item.suffix in IMAGE_EXTENSIONS])
        payload.append(
            {
                "scene": scene_dir.name,
                "image_count": str(image_count),
                "path": str(scene_dir),
                "mtime": format_mtime(scene_dir),
            }
        )
    return payload


def discover_scene_datasets(scene_data_root: Path, limit: int = 200) -> List[Dict[str, str]]:
    if not scene_data_root.exists():
        return []
    candidates = [item for item in scene_data_root.iterdir() if item.is_dir()]
    candidates.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)

    payload: List[Dict[str, str]] = []
    for scene_dir in candidates[:limit]:
        image_dir = scene_dir / "images"
        image_count = (
            len([item for item in image_dir.iterdir() if item.is_file() and item.suffix in IMAGE_EXTENSIONS])
            if image_dir.exists()
            else 0
        )
        ply_files = list(scene_dir.glob("*.ply"))
        payload.append(
            {
                "scene": scene_dir.name,
                "image_count": str(image_count),
                "pointcloud_count": str(len(ply_files)),
                "has_transforms": str((scene_dir / "transforms.json").exists()),
                "path": str(scene_dir),
                "mtime": format_mtime(scene_dir),
            }
        )
    return payload


def read_latest_scene(scene_data_root: Path) -> str:
    marker = scene_data_root / "LATEST_SCENE.txt"
    if not marker.exists():
        return ""
    return marker.read_text(encoding="utf-8").strip()
