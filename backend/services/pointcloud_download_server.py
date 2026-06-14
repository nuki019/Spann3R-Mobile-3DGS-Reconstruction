import os
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from services.pointcloud_index import (
    DEFAULT_POINTCLOUD_ROOTS,
    discover_pointclouds as discover_pointcloud_items,
    index_by_id as index_pointclouds_by_id,
    infer_pointcloud_variant as infer_pointcloud_variant_for_path,
    parse_pointcloud_roots,
    select_latest_pointcloud,
    under_allowed_roots as is_under_allowed_roots,
)

DEFAULT_ROOTS = DEFAULT_POINTCLOUD_ROOTS
ROOTS = parse_pointcloud_roots(os.getenv("POINTCLOUD_ROOTS", ""), DEFAULT_ROOTS)

app = FastAPI(title="PointCloud Download Service")


def under_allowed_roots(path: Path) -> bool:
    return is_under_allowed_roots(path, ROOTS)


def infer_pointcloud_variant(file_path: Path) -> str:
    return infer_pointcloud_variant_for_path(file_path)


def discover_pointclouds() -> List[Dict[str, str]]:
    return discover_pointcloud_items(ROOTS)


def index_by_id() -> Dict[str, Path]:
    return index_pointclouds_by_id(discover_pointclouds())


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
    chosen = select_latest_pointcloud(items, prefer=prefer)
    if not chosen:
        if prefer == "gaussian":
            raise HTTPException(
                status_code=404,
                detail="未找到 Gaussian 训练点云（当前可能仍在训练中或尚未导出）",
            )
        raise HTTPException(status_code=404, detail=f"未找到类型为 {prefer} 的点云")
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
