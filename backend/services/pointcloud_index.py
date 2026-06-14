"""Pure point cloud discovery and selection helpers.

This module intentionally avoids FastAPI imports so the delivery smoke tests can
exercise download-list behavior on a local machine without installing backend
server dependencies.
"""

from __future__ import annotations

import hashlib
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional


DEFAULT_POINTCLOUD_ROOTS = [
    "/root/autodl-tmp/gs_train",
    "/root/autodl-tmp/Spann3R/output/demo",
    "/root/autodl-tmp/Spann3R/output",
]

VARIANT_ORDER = {
    "gaussian": ("gaussian", "downsampled", "train", "raw", "other"),
    "downsampled": ("downsampled", "train", "raw", "gaussian", "other"),
    "train": ("train", "downsampled", "raw", "gaussian", "other"),
    "raw": ("raw", "downsampled", "train", "gaussian", "other"),
    "other": ("other",),
    "any": ("gaussian", "downsampled", "train", "raw", "other"),
}


def parse_pointcloud_roots(raw_value: str, defaults: Iterable[str]) -> List[Path]:
    value = raw_value.strip() if raw_value else ""
    source = value or ",".join(defaults)
    return [Path(item.strip()).resolve() for item in source.split(",") if item.strip()]


def under_allowed_roots(path: Path, roots: Iterable[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(Path(root).resolve())
            return True
        except ValueError:
            continue
    return False


def infer_pointcloud_variant(file_path: Path) -> str:
    path_text = str(file_path).lower()
    name = file_path.name.lower()
    if "_gaussian_" in name or "gaussian_export" in path_text:
        return "gaussian"
    if name.startswith("point_cloud") and "splatfacto" in path_text:
        return "gaussian"
    if "_downsampled" in name:
        return "downsampled"
    if "_raw" in name:
        return "raw"
    if "_init" in name:
        return "train"
    return "other"


def infer_scene_name(file_path: Path) -> str:
    parts = file_path.resolve().parts
    for marker in ("scenes", "outputs", "demo"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts):
                return parts[index + 1]
    return file_path.parent.name


def discover_pointclouds(roots: Iterable[Path]) -> List[Dict[str, str]]:
    allowed_roots = [Path(root).resolve() for root in roots]
    files: List[Path] = []
    for root in allowed_roots:
        if root.exists():
            files.extend(root.rglob("*.ply"))

    sortable_files = []
    for file_path in files:
        try:
            stat = file_path.stat()
        except OSError:
            continue
        sortable_files.append((file_path, stat))
    sortable_files.sort(key=lambda item: item[1].st_mtime_ns, reverse=True)

    payload: List[Dict[str, str]] = []
    for file_path, stat in sortable_files:
        if not under_allowed_roots(file_path, allowed_roots):
            continue
        file_id = hashlib.sha1(str(file_path).encode("utf-8")).hexdigest()[:16]
        payload.append(
            {
                "id": file_id,
                "name": file_path.name,
                "scene": infer_scene_name(file_path),
                "variant": infer_pointcloud_variant(file_path),
                "path": str(file_path),
                "size_bytes": str(stat.st_size),
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "download_url": f"/download/{file_id}",
            }
        )
    return payload


def pick_preferred_pointcloud(
    items: List[Dict[str, str]],
    prefer: str = "gaussian",
    strict: bool = False,
    latest_scene: str = "",
) -> Optional[Dict[str, str]]:
    if not items:
        return None

    prefer = (prefer or "gaussian").strip().lower()
    if strict:
        strict_order = {
            "gaussian": ("gaussian",),
            "downsampled": ("downsampled",),
            "train": ("train",),
            "raw": ("raw",),
            "other": ("other",),
            "any": VARIANT_ORDER["any"],
        }
        variant_order = strict_order.get(prefer, strict_order["gaussian"])
    else:
        variant_order = VARIANT_ORDER.get(prefer, VARIANT_ORDER["gaussian"])

    scoped = [item for item in items if item.get("scene") == latest_scene] if latest_scene else []
    ordered_groups = [scoped, items] if scoped else [items]

    for group in ordered_groups:
        for preferred_variant in variant_order:
            for item in group:
                if item.get("variant") == preferred_variant:
                    return item
    if strict:
        return None
    return items[0]


def index_by_id(items: Iterable[Dict[str, str]]) -> Dict[str, Path]:
    mapping: Dict[str, Path] = {}
    for item in items:
        file_id = item.get("id")
        file_path = item.get("path")
        if file_id and file_path:
            mapping[file_id] = Path(file_path)
    return mapping


def human_size(size_bytes: int) -> str:
    value = float(max(size_bytes, 0))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} GB"


def summarize_pointclouds(items: List[Dict[str, str]]) -> Dict[str, object]:
    total_size = 0
    scenes: Dict[str, int] = {}
    for item in items:
        try:
            total_size += int(item.get("size_bytes") or 0)
        except ValueError:
            pass
        scene = item.get("scene") or "-"
        scenes[scene] = scenes.get(scene, 0) + 1
    return {
        "count": len(items),
        "total_size": human_size(total_size),
        "latest": items[0] if items else None,
        "scenes": scenes,
    }


def build_pointclouds_summary_payload(
    items: List[Dict[str, str]],
    limit: int = 300,
) -> Dict[str, object]:
    return {
        "summary": summarize_pointclouds(items),
        "items": items[:limit],
    }


def is_processed_pointcloud(item: Dict[str, str]) -> bool:
    name = (item.get("name") or "").lower()
    return "clipped" in name or "downsampled" in name or name.endswith("_init.ply")


def filter_pointclouds_by_processed(
    items: List[Dict[str, str]],
    processed: Optional[bool],
) -> List[Dict[str, str]]:
    if processed is None:
        return items
    return [item for item in items if is_processed_pointcloud(item) == processed]


def normalize_prefer(value: str, default: str = "gaussian") -> str:
    return (value or default).strip().lower() or default


def select_latest_pointcloud(
    items: List[Dict[str, str]],
    prefer: str = "gaussian",
    processed: Optional[bool] = None,
    strict: Optional[bool] = None,
) -> Optional[Dict[str, str]]:
    candidates = filter_pointclouds_by_processed(items, processed)
    prefer_key = normalize_prefer(prefer)
    strict_value = prefer_key != "any" if strict is None else strict
    return pick_preferred_pointcloud(candidates, prefer=prefer_key, strict=strict_value)


def select_scene_pointcloud(
    items: List[Dict[str, str]],
    scene_name: str,
    prefer: str = "gaussian",
    processed: Optional[bool] = None,
    strict: Optional[bool] = None,
) -> Optional[Dict[str, str]]:
    scene_key = scene_name.strip()
    candidates = [
        item
        for item in filter_pointclouds_by_processed(items, processed)
        if item.get("scene") == scene_key
    ]
    prefer_key = normalize_prefer(prefer)
    strict_value = prefer_key != "any" if strict is None else strict
    return pick_preferred_pointcloud(candidates, prefer=prefer_key, strict=strict_value)


def select_zip_pointclouds(
    items: List[Dict[str, str]],
    ids: str = "",
    variant: str = "gaussian",
    processed: Optional[bool] = None,
    latest_scene: str = "",
) -> List[Dict[str, str]]:
    if ids.strip():
        wanted = {item.strip() for item in ids.split(",") if item.strip()}
        return [item for item in items if item.get("id") in wanted]

    variant_key = normalize_prefer(variant, default="gaussian")
    selected = [
        item
        for item in items
        if (variant_key == "any" or item.get("variant") == variant_key)
        and (not latest_scene or item.get("scene") == latest_scene)
    ]
    return filter_pointclouds_by_processed(selected, processed)


def build_zip_archive_name(latest_scene: str, variant: str) -> str:
    archive_scene = latest_scene or "pointclouds"
    archive_variant = normalize_prefer(variant, default="any")
    return f"{archive_scene}_{archive_variant}.zip"


def write_pointcloud_zip(
    items: List[Dict[str, str]],
    roots: Iterable[Path],
    archive_path: Optional[Path] = None,
) -> Path:
    if archive_path is None:
        tmp = tempfile.NamedTemporaryFile(prefix="pointclouds_", suffix=".zip", delete=False)
        archive_path = Path(tmp.name)
        tmp.close()

    allowed_roots = [Path(root).resolve() for root in roots]
    used_names: Dict[str, int] = {}
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in items:
            path = Path(item["path"])
            if not path.exists() or not under_allowed_roots(path, allowed_roots):
                continue
            arcname = f"{item.get('scene') or 'scene'}_{path.name}"
            count = used_names.get(arcname, 0)
            used_names[arcname] = count + 1
            if count:
                stem = Path(arcname).stem
                suffix = Path(arcname).suffix
                arcname = f"{stem}_{count}{suffix}"
            archive.write(path, arcname=arcname)
    return archive_path


def find_scene_gaussian_files(scene_name: str, items: List[Dict[str, str]]) -> Dict[str, str]:
    if not scene_name:
        return {}
    scene_items = [
        item
        for item in items
        if item.get("scene") == scene_name and item.get("variant") == "gaussian"
    ]
    raw = ""
    clipped = ""
    for item in scene_items:
        name = (item.get("name") or "").lower()
        if not clipped and "clipped" in name:
            clipped = item.get("name") or ""
        if not raw and ("_gaussian_raw" in name or name == "splat.ply"):
            raw = item.get("name") or ""
    if not raw:
        for item in scene_items:
            name = (item.get("name") or "").lower()
            if name == "point_cloud.ply":
                raw = item.get("name") or ""
                break
    return {
        "raw": raw,
        "clipped": clipped,
    }
