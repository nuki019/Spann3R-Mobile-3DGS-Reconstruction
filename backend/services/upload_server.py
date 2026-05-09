from datetime import datetime
from pathlib import Path
from typing import Dict
import os
import secrets
import uuid

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
VALID_EXTENSIONS = {".jpg", ".jpeg", ".png"}
CHUNK_SIZE = 1024 * 1024

SAVE_DIR = Path(os.getenv("UPLOAD_SAVE_DIR", "/root/autodl-tmp/input_images"))
AUTH_TOKEN = os.getenv("UPLOAD_AUTH_TOKEN", "").strip()
MAX_FILE_SIZE_MB = int(os.getenv("UPLOAD_MAX_FILE_SIZE_MB", "25"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOW_ORIGINS = [item for item in os.getenv("UPLOAD_ALLOW_ORIGINS", "*").split(",") if item]

SAVE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Spann3R Upload Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_STATS: Dict[str, int] = {
    "files": 0,
    "bytes": 0,
}


def validate_token(form_token: str, header_token: str) -> None:
    if not AUTH_TOKEN:
        return
    token = form_token or header_token
    if not secrets.compare_digest(token, AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="鉴权失败，无效 token")


def validate_file_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in VALID_EXTENSIONS:
        raise HTTPException(status_code=400, detail="仅支持 jpg/jpeg/png 格式")
    return suffix


@app.get("/")
async def root():
    return {
        "service": "upload",
        "status": "ok",
        "message": "上传服务运行中。请使用 POST /upload 上传图片，或 GET /stats 查看统计。",
    }


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "save_dir": str(SAVE_DIR)}


@app.get("/stats")
async def stats():
    return {
        "uploaded_files": UPLOAD_STATS["files"],
        "uploaded_bytes": UPLOAD_STATS["bytes"],
        "save_dir": str(SAVE_DIR),
        "max_file_size_mb": MAX_FILE_SIZE_MB,
    }


@app.post("/upload")
async def upload_frame(
    frame_file: UploadFile = File(...),
    token: str = Form(default=""),
    x_auth_token: str = Header(default="", alias="X-Auth-Token"),
):
    validate_token(token, x_auth_token)
    suffix = validate_file_extension(frame_file.filename or "")

    filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S_%f')}_{uuid.uuid4().hex[:8]}{suffix}"
    save_path = SAVE_DIR / filename

    total_bytes = 0
    try:
        with save_path.open("wb") as handle:
            while True:
                chunk = await frame_file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_FILE_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过大小限制 {MAX_FILE_SIZE_MB}MB",
                    )
                handle.write(chunk)
    except HTTPException:
        if save_path.exists():
            save_path.unlink()
        raise
    except Exception as error:
        if save_path.exists():
            save_path.unlink()
        raise HTTPException(status_code=500, detail=f"文件保存失败: {error}")
    finally:
        await frame_file.close()

    UPLOAD_STATS["files"] += 1
    UPLOAD_STATS["bytes"] += total_bytes
    return {
        "code": 200,
        "msg": "上传成功",
        "filename": filename,
        "bytes": total_bytes,
    }

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("UPLOAD_PORT", "6008"))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
    )
