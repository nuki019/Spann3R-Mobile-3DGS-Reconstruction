import hashlib
import os
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

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
    for root in ROOTS:
        if root.exists():
            files.extend(root.rglob("*.ply"))
    files = sorted(files, key=lambda p: p.stat().st_mtime_ns, reverse=True)

    payload = []
    for file_path in files:
        if not under_allowed_roots(file_path):
            continue
        file_id = hashlib.sha1(str(file_path).encode("utf-8")).hexdigest()[:16]
        payload.append(
            {
                "id": file_id,
                "name": file_path.name,
                "variant": infer_pointcloud_variant(file_path),
                "path": str(file_path),
                "size_bytes": str(file_path.stat().st_size),
                "mtime": str(file_path.stat().st_mtime),
                "download_url": f"/download/{file_id}",
            }
        )
    return payload


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


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    files = discover_pointclouds()
    rows = []
    for item in files[:200]:
        rows.append(
            f"<tr><td>{item['variant']}</td><td>{item['name']}</td><td>{item['size_bytes']}</td><td>{item['path']}</td>"
            f"<td><a href='{item['download_url']}'>下载</a></td></tr>"
        )
    table = "\n".join(rows) or "<tr><td colspan='5'>暂无 .ply 文件</td></tr>"
    return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>点云下载 (6008)</title>
  <style>
    body {{ font-family: sans-serif; margin: 24px; background:#0f172a; color:#e2e8f0; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border: 1px solid #334155; padding: 8px; word-break: break-all; }}
    a {{ color: #38bdf8; }}
  </style>
</head>
<body>
  <h1>训练点云下载</h1>
  <p>可用目录: {", ".join(str(root) for root in ROOTS)}</p>
  <p>
    <a href="/download/latest?prefer=gaussian">下载最新 Gaussian 点云</a> |
    <a href="/download/latest?prefer=downsampled">下载最新 Spann3R 下采样点云</a> |
    <a href="/files">JSON列表</a>
  </p>
  <table>
    <thead><tr><th>类型</th><th>文件名</th><th>大小(bytes)</th><th>路径</th><th>操作</th></tr></thead>
    <tbody>{table}</tbody>
  </table>
</body>
</html>
"""


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "roots": [str(root) for root in ROOTS]}


@app.get("/files")
async def files():
    return {"items": discover_pointclouds()}


@app.get("/download/latest")
async def download_latest(prefer: str = "gaussian"):
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
    path = Path(chosen["path"])
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.get("/download/{file_id}")
async def download_by_id(file_id: str):
    mapping = index_by_id()
    if file_id not in mapping:
        raise HTTPException(status_code=404, detail="文件不存在或已过期")
    path = mapping[file_id]
    if not path.exists() or not under_allowed_roots(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("POINTCLOUD_PORT", "6008"))
    uvicorn.run(app, host="0.0.0.0", port=port)
