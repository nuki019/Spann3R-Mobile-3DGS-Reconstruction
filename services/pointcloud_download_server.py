import hashlib
import html
import os
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask

DEFAULT_ROOTS = [
    "/root/autodl-tmp/gs_train",
    "/root/autodl-tmp/Spann3R/output/demo",
    "/root/autodl-tmp/Spann3R/output",
]

ROOTS = [
    Path(item.strip()).resolve()
    for item in os.getenv("POINTCLOUD_ROOTS", ",".join(DEFAULT_ROOTS)).split(",")
    if item.strip()
]
POINTCLOUD_CACHE_DIR = Path(os.getenv("POINTCLOUD_CACHE_DIR", "/root/autodl-tmp/pointcloud_processed_cache")).resolve()
PROCESSED_DOWNLOAD_VOXEL_SIZE = float(os.getenv("PROCESSED_DOWNLOAD_VOXEL_SIZE", "0.02"))
PROCESSED_DOWNLOAD_PADDING_RATIO = float(os.getenv("PROCESSED_DOWNLOAD_PADDING_RATIO", "0.03"))
PROCESSED_DOWNLOAD_MAX_AGE_HOURS = float(os.getenv("PROCESSED_DOWNLOAD_MAX_AGE_HOURS", "24"))
PROCESSED_DOWNLOAD_MAX_FILES = int(os.getenv("PROCESSED_DOWNLOAD_MAX_FILES", "12"))

app = FastAPI(title="PointCloud Download Service")


def under_allowed_roots(path: Path) -> bool:
    resolved = path.resolve()
    for root in ROOTS:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def is_downloadable_path(path: Path) -> bool:
    resolved = path.resolve()
    if under_allowed_roots(resolved):
        return True
    try:
        resolved.relative_to(POINTCLOUD_CACHE_DIR)
        return True
    except ValueError:
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


def discover_pointclouds() -> List[Dict[str, str]]:
    files: List[Path] = []
    seen_paths = set()
    for root in ROOTS:
        if root.exists():
            for file_path in root.rglob("*.ply"):
                resolved = file_path.resolve()
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                files.append(resolved)
    files = sorted(files, key=lambda p: p.stat().st_mtime_ns, reverse=True)

    payload = []
    for file_path in files:
        if not under_allowed_roots(file_path):
            continue
        stat = file_path.stat()
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


def infer_scene_name(file_path: Path) -> str:
    parts = file_path.resolve().parts
    for marker in ("scenes", "outputs", "demo"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts):
                return parts[index + 1]
    return file_path.parent.name


def pick_preferred_pointcloud(
    items: List[Dict[str, str]],
    prefer: str = "gaussian",
    strict: bool = False,
) -> Dict[str, str]:
    if not items:
        raise ValueError("empty pointcloud list")
    prefer = (prefer or "gaussian").strip().lower()
    if strict:
        order_map = {
            "gaussian": ("gaussian",),
            "downsampled": ("downsampled",),
            "train": ("train",),
            "raw": ("raw",),
            "other": ("other",),
            "any": ("gaussian", "downsampled", "train", "raw", "other"),
        }
    else:
        order_map = {
            "gaussian": ("gaussian", "downsampled", "train", "raw", "other"),
            "downsampled": ("downsampled", "train", "raw", "gaussian", "other"),
            "train": ("train", "downsampled", "raw", "gaussian", "other"),
            "raw": ("raw", "downsampled", "train", "gaussian", "other"),
            "any": ("gaussian", "downsampled", "train", "raw", "other"),
        }
    for preferred_variant in order_map.get(prefer, order_map["gaussian"]):
        for item in items:
            if item.get("variant") == preferred_variant:
                return item
    if strict:
        raise ValueError(f"no pointcloud matched prefer={prefer}")
    return items[0]


def index_by_id() -> Dict[str, Path]:
    mapping: Dict[str, Path] = {}
    for item in discover_pointclouds():
        mapping[item["id"]] = Path(item["path"])
    return mapping


def format_bytes(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    size_kb = size_bytes / 1024
    if size_kb < 1024:
        return f"{size_kb:.2f} KB"
    size_mb = size_kb / 1024
    if size_mb < 1024:
        return f"{size_mb:.2f} MB"
    return f"{size_mb / 1024:.2f} GB"


def summarize_pointclouds(items: List[Dict[str, str]]) -> Dict[str, object]:
    scene_map: Dict[str, int] = {}
    variant_map: Dict[str, int] = {}
    total_bytes = 0
    for item in items:
        scene_map[item["scene"]] = scene_map.get(item["scene"], 0) + 1
        variant_map[item["variant"]] = variant_map.get(item["variant"], 0) + 1
        try:
            total_bytes += int(item["size_bytes"])
        except (TypeError, ValueError):
            pass
    return {
        "count": len(items),
        "total_bytes": total_bytes,
        "total_size": format_bytes(total_bytes),
        "latest": items[0] if items else None,
        "scenes": scene_map,
        "variants": variant_map,
    }


def filter_pointclouds(
    items: List[Dict[str, str]],
    scene: str = "",
    variant: str = "",
    ids: str = "",
) -> List[Dict[str, str]]:
    selected = items
    scene = (scene or "").strip()
    variant = (variant or "").strip().lower()
    id_set = {item.strip() for item in (ids or "").split(",") if item.strip()}
    if id_set:
        selected = [item for item in selected if item["id"] in id_set]
    if scene:
        selected = [item for item in selected if item["scene"] == scene]
    if variant and variant != "any":
        selected = [item for item in selected if item["variant"] == variant]
    return selected


def build_zip_response(items: List[Dict[str, str]], archive_prefix: str) -> FileResponse:
    if not items:
        raise HTTPException(status_code=404, detail="没有匹配的点云文件可打包")

    safe_prefix = re.sub(r"[^A-Za-z0-9_-]+", "_", archive_prefix).strip("_") or "pointclouds"
    temp = tempfile.NamedTemporaryFile(prefix=f"{safe_prefix}_", suffix=".zip", delete=False)
    zip_path = Path(temp.name)
    temp.close()

    written = 0
    used_names: Dict[str, int] = {}
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in items:
            path = Path(item["path"])
            if not path.exists() or not is_downloadable_path(path):
                continue
            arcname = f"{item['scene']}/{item['variant']}/{path.name}"
            if arcname in used_names:
                used_names[arcname] += 1
                stem = Path(arcname).stem
                suffix = Path(arcname).suffix
                arcname = str(Path(arcname).with_name(f"{stem}_{used_names[arcname]}{suffix}"))
            else:
                used_names[arcname] = 1
            archive.write(path, arcname)
            written += 1

    if written <= 0:
        zip_path.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="没有可写入压缩包的点云文件")

    return FileResponse(
        zip_path,
        filename=f"{safe_prefix}.zip",
        media_type="application/zip",
        background=BackgroundTask(lambda: zip_path.unlink(missing_ok=True)),
    )


def parse_bool_query(value: str, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def prune_processed_cache() -> None:
    if not POINTCLOUD_CACHE_DIR.exists():
        return
    files = [item for item in POINTCLOUD_CACHE_DIR.glob("*.ply") if item.is_file()]
    now = datetime.now().timestamp()
    max_age_seconds = max(PROCESSED_DOWNLOAD_MAX_AGE_HOURS, 0.5) * 3600
    for file_path in files:
        try:
            if now - file_path.stat().st_mtime > max_age_seconds:
                file_path.unlink(missing_ok=True)
        except OSError:
            continue

    files = [item for item in POINTCLOUD_CACHE_DIR.glob("*.ply") if item.is_file()]
    files.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)
    for old_file in files[max(PROCESSED_DOWNLOAD_MAX_FILES, 1):]:
        old_file.unlink(missing_ok=True)


def find_reference_pointcloud(item: Dict[str, str], items: List[Dict[str, str]]) -> Optional[Path]:
    if item.get("variant") in {"downsampled", "train", "raw"}:
        return None
    scene = item.get("scene", "")
    for candidate in items:
        if candidate.get("scene") == scene and candidate.get("variant") == "downsampled":
            reference = Path(candidate["path"])
            if reference.exists() and under_allowed_roots(reference):
                return reference
    return None


def processed_cache_path(source: Path, reference: Optional[Path], voxel_size: float, padding_ratio: float) -> Path:
    source_stat = source.stat()
    ref_part = ""
    if reference and reference.exists():
        ref_stat = reference.stat()
        ref_part = f"|{reference}|{ref_stat.st_size}|{ref_stat.st_mtime_ns}"
    key = hashlib.sha1(
        (
            f"{source}|{source_stat.st_size}|{source_stat.st_mtime_ns}"
            f"{ref_part}|voxel={voxel_size:.6f}|padding={padding_ratio:.6f}"
        ).encode("utf-8")
    ).hexdigest()[:16]
    return POINTCLOUD_CACHE_DIR / f"{source.stem}_processed_{key}{source.suffix or '.ply'}"


def process_pointcloud_for_download(
    source: Path,
    reference: Optional[Path],
    voxel_size: float,
    padding_ratio: float,
) -> Path:
    if not source.exists() or not under_allowed_roots(source):
        raise HTTPException(status_code=404, detail="点云文件不存在")

    voxel_size = max(float(voxel_size), 0.0)
    padding_ratio = max(float(padding_ratio), 0.0)
    POINTCLOUD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    prune_processed_cache()
    output = processed_cache_path(source, reference, voxel_size, padding_ratio)
    if output.exists() and output.stat().st_size > 0:
        return output

    try:
        import numpy as np
        import open3d as o3d
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"点云处理依赖不可用: {error}") from error

    source_cloud = o3d.io.read_point_cloud(str(source))
    if len(source_cloud.points) <= 0:
        raise HTTPException(status_code=400, detail="点云为空，无法处理")

    working_cloud = source_cloud
    if reference and reference.exists() and under_allowed_roots(reference):
        reference_cloud = o3d.io.read_point_cloud(str(reference))
        if len(reference_cloud.points) > 0:
            source_points = np.asarray(working_cloud.points)
            reference_points = np.asarray(reference_cloud.points)
            ref_min = reference_points.min(axis=0)
            ref_max = reference_points.max(axis=0)
            ref_extent = np.maximum(ref_max - ref_min, 1e-6)
            padding = ref_extent * padding_ratio
            keep_mask = np.logical_and(
                source_points >= (ref_min - padding),
                source_points <= (ref_max + padding),
            ).all(axis=1)
            keep_indices = np.where(keep_mask)[0]
            if keep_indices.size > 0:
                working_cloud = working_cloud.select_by_index(keep_indices.tolist())

    if voxel_size > 0 and len(working_cloud.points) > 0:
        working_cloud = working_cloud.voxel_down_sample(voxel_size)

    if len(working_cloud.points) <= 0:
        raise HTTPException(status_code=400, detail="裁切/下采样后点云为空，请降低处理强度")

    ok = o3d.io.write_point_cloud(str(output), working_cloud)
    if not ok or not output.exists():
        raise HTTPException(status_code=500, detail="处理后点云写入失败")
    return output


def resolve_download_path(
    item: Dict[str, str],
    all_items: List[Dict[str, str]],
    processed: bool,
    voxel_size: float = PROCESSED_DOWNLOAD_VOXEL_SIZE,
    padding_ratio: float = PROCESSED_DOWNLOAD_PADDING_RATIO,
) -> Path:
    source = Path(item["path"])
    if not processed:
        return source
    reference = find_reference_pointcloud(item, all_items)
    return process_pointcloud_for_download(source, reference, voxel_size, padding_ratio)


@app.get("/", response_class=HTMLResponse)
async def home(scene: str = "", variant: str = "") -> str:
    all_files = discover_pointclouds()
    files = filter_pointclouds(all_files, scene=scene, variant=variant)
    summary = summarize_pointclouds(files)
    scene_options = sorted(summarize_pointclouds(all_files)["scenes"].keys())
    variant_options = ["any", "gaussian", "downsampled", "train", "raw", "other"]
    selected_variant = (variant or "any").lower()

    scene_select = ["<option value=''>全部场景</option>"]
    for scene_name in scene_options:
        selected = " selected" if scene_name == scene else ""
        escaped = html.escape(scene_name)
        scene_select.append(f"<option value='{escaped}'{selected}>{escaped}</option>")

    variant_select = []
    for variant_name in variant_options:
        selected = " selected" if variant_name == selected_variant else ""
        label = "全部类型" if variant_name == "any" else variant_name
        variant_select.append(f"<option value='{variant_name}'{selected}>{label}</option>")

    rows = []
    for item in files[:200]:
        size_text = format_bytes(int(item["size_bytes"]))
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['scene'])}</td>"
            f"<td>{html.escape(item['variant'])}</td>"
            f"<td>{html.escape(item['name'])}</td>"
            f"<td>{size_text}</td>"
            f"<td>{html.escape(item['mtime'])}</td>"
            f"<td>{html.escape(item['path'])}</td>"
            f"<td><a href='{item['download_url']}'>单文件</a> · <a href='/download/zip?ids={item['id']}'>ZIP</a></td>"
            "</tr>"
        )
    table = "\n".join(rows) or "<tr><td colspan='7'>暂无 .ply 文件</td></tr>"
    zip_query = f"scene={html.escape(scene)}&variant={html.escape(selected_variant)}"
    return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>点云下载 (6008)</title>
  <style>
    body {{ font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif; margin: 24px; background:#0f172a; color:#e2e8f0; }}
    .toolbar {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:14px 0; }}
    select, button {{ border:1px solid #334155; border-radius:10px; padding:8px 10px; background:#0b1223; color:#e2e8f0; }}
    button {{ background:#2563eb; cursor:pointer; }}
    .stat {{ display:inline-block; border:1px solid #334155; border-radius:999px; padding:5px 10px; margin-right:8px; color:#bae6fd; }}
    table {{ width: 100%; border-collapse: collapse; background:#11192c; }}
    th, td {{ border-bottom: 1px solid #334155; padding: 8px; word-break: break-all; font-size:13px; text-align:left; }}
    th {{ background:#0b1223; }}
    a {{ color: #38bdf8; text-decoration:none; }}
  </style>
</head>
<body>
  <h1>训练点云下载</h1>
  <p>可用目录: {", ".join(str(root) for root in ROOTS)}</p>
  <form class="toolbar" method="get" action="/">
    <select name="scene">{"".join(scene_select)}</select>
    <select name="variant">{"".join(variant_select)}</select>
    <button type="submit">筛选</button>
  </form>
  <p>
    <a href="/download/processed/latest?prefer=gaussian">下载优化后 Gaussian 点云</a> |
    <a href="/download/latest?prefer=gaussian&processed=false">下载原始 Gaussian 点云</a> |
    <a href="/download/processed/latest?prefer=downsampled">下载优化后 Spann3R 点云</a> |
    <a href="/download/zip?{zip_query}">打包当前筛选结果</a> |
    <a href="/files">JSON列表</a>
  </p>
  <p><span class="stat">文件数 {summary["count"]}</span><span class="stat">总大小 {summary["total_size"]}</span></p>
  <table>
    <thead><tr><th>场景</th><th>类型</th><th>文件名</th><th>大小</th><th>更新时间</th><th>路径</th><th>操作</th></tr></thead>
    <tbody>{table}</tbody>
  </table>
</body>
</html>
"""


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "roots": [str(root) for root in ROOTS]}


@app.get("/files")
async def files(scene: str = "", variant: str = "", ids: str = ""):
    items = filter_pointclouds(discover_pointclouds(), scene=scene, variant=variant, ids=ids)
    return {"summary": summarize_pointclouds(items), "items": items}


@app.get("/download/zip")
async def download_zip(
    scene: str = "",
    variant: str = "",
    ids: str = "",
    processed: str = "true",
    voxel_size: float = PROCESSED_DOWNLOAD_VOXEL_SIZE,
    padding_ratio: float = PROCESSED_DOWNLOAD_PADDING_RATIO,
):
    items = filter_pointclouds(discover_pointclouds(), scene=scene, variant=variant, ids=ids)
    if parse_bool_query(processed, True):
        all_items = discover_pointclouds()
        processed_items = []
        for item in items:
            output = resolve_download_path(item, all_items, True, voxel_size, padding_ratio)
            processed_item = item.copy()
            processed_item["path"] = str(output)
            processed_item["name"] = output.name
            processed_item["size_bytes"] = str(output.stat().st_size)
            processed_items.append(processed_item)
        items = processed_items
    prefix_parts = ["pointclouds"]
    if scene:
        prefix_parts.append(scene)
    if variant and variant != "any":
        prefix_parts.append(variant)
    if ids:
        prefix_parts.append("selected")
    if parse_bool_query(processed, True):
        prefix_parts.append("processed")
    return build_zip_response(items, "_".join(prefix_parts))


@app.get("/download/latest")
async def download_latest(
    prefer: str = "gaussian",
    processed: str = "true",
    voxel_size: float = PROCESSED_DOWNLOAD_VOXEL_SIZE,
    padding_ratio: float = PROCESSED_DOWNLOAD_PADDING_RATIO,
):
    items = discover_pointclouds()
    if not items:
        raise HTTPException(status_code=404, detail="未找到可下载点云")
    prefer = (prefer or "gaussian").strip().lower()
    strict = prefer != "any"
    try:
        chosen = pick_preferred_pointcloud(items, prefer=prefer, strict=strict)
    except ValueError:
        if prefer == "gaussian":
            raise HTTPException(
                status_code=404,
                detail="未找到 Gaussian 训练点云（当前可能仍在训练中或尚未导出）",
            ) from None
        raise HTTPException(status_code=404, detail=f"未找到类型为 {prefer} 的点云") from None
    path = resolve_download_path(
        chosen,
        items,
        parse_bool_query(processed, True),
        voxel_size,
        padding_ratio,
    )
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.get("/download/processed/latest")
async def download_processed_latest(
    prefer: str = "gaussian",
    voxel_size: float = PROCESSED_DOWNLOAD_VOXEL_SIZE,
    padding_ratio: float = PROCESSED_DOWNLOAD_PADDING_RATIO,
):
    return await download_latest(
        prefer=prefer,
        processed="true",
        voxel_size=voxel_size,
        padding_ratio=padding_ratio,
    )


@app.get("/download/{file_id}")
async def download_by_id(
    file_id: str,
    processed: str = "true",
    voxel_size: float = PROCESSED_DOWNLOAD_VOXEL_SIZE,
    padding_ratio: float = PROCESSED_DOWNLOAD_PADDING_RATIO,
):
    items = discover_pointclouds()
    item = next((entry for entry in items if entry["id"] == file_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="文件不存在或已过期")
    path = resolve_download_path(
        item,
        items,
        parse_bool_query(processed, True),
        voxel_size,
        padding_ratio,
    )
    if not path.exists() or not is_downloadable_path(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("POINTCLOUD_PORT", "6008"))
    uvicorn.run(app, host="0.0.0.0", port=port)
