import os
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from services.pointcloud_index import (
    DEFAULT_POINTCLOUD_ROOTS,
    build_index_download_decision,
    build_latest_download_decision,
    discover_pointclouds as discover_pointcloud_items,
    index_by_id as index_pointclouds_by_id,
    parse_pointcloud_roots,
)

DEFAULT_ROOTS = DEFAULT_POINTCLOUD_ROOTS
ROOTS = parse_pointcloud_roots(os.getenv("POINTCLOUD_ROOTS", ""), DEFAULT_ROOTS)

app = FastAPI(title="PointCloud Download Service")


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
    decision = build_latest_download_decision(discover_pointclouds(), prefer=prefer)
    if not decision["ok"]:
        raise HTTPException(status_code=int(decision["status_code"]), detail=str(decision["detail"]))
    chosen = decision["item"]
    path = Path(chosen["path"])
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.get("/download/{file_id}")
async def download_by_id(file_id: str):
    decision = build_index_download_decision(index_by_id(), file_id, ROOTS)
    if not decision["ok"]:
        raise HTTPException(status_code=int(decision["status_code"]), detail=str(decision["detail"]))
    path = Path(decision["path"])
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("POINTCLOUD_PORT", "6008"))
    uvicorn.run(app, host="0.0.0.0", port=port)
