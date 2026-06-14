import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from pipeline.job_queue import (
    list_jobs,
    record_uploaded_frame,
    sanitize_job_id,
    summarize_jobs,
)
from pipeline.job_policy import can_cancel_job_status, can_upload_by_phase
from pipeline.task_state import PipelineStateStore, build_sections
from services.pointcloud_index import (
    DEFAULT_POINTCLOUD_ROOTS,
    discover_pointclouds as discover_pointcloud_items,
    filter_pointclouds_by_processed,
    find_scene_gaussian_files as find_scene_gaussian_files_for_items,
    index_by_id as index_pointclouds_by_id,
    infer_pointcloud_variant as infer_pointcloud_variant_for_path,
    parse_pointcloud_roots,
    pick_preferred_pointcloud as pick_preferred_pointcloud_item,
    summarize_pointclouds,
    under_allowed_roots as is_under_allowed_roots,
    write_pointcloud_zip,
)
from services.config_model import (
    get_config_bool as get_config_bool_from_values,
    get_config_path as get_config_path_from_values,
    read_config_file,
    write_config_file,
)
from services.progress_model import build_phase_status, extract_current_run_logs, parse_progress
from services.upload_model import (
    build_upload_filename,
    resolve_upload_destination,
    validate_upload_suffix,
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"}
UPLOAD_CHUNK_SIZE = 1024 * 1024

ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

PIPELINE_SCRIPT = ROOT_DIR / "pipeline" / "backend_4090.py"
PIPELINE_MODULE = "pipeline.backend_4090"
PIPELINE_PID_FILE = LOG_DIR / "backend_4090.pid"
PIPELINE_LOG_FILE = LOG_DIR / "backend_4090.log"
ENV_FILE = ROOT_DIR / ".env.pipeline.4090"
STATE_STORE = PipelineStateStore()
DASHBOARD_AUTH_TOKEN = os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()
UPLOAD_AUTH_TOKEN = os.getenv("UPLOAD_AUTH_TOKEN", "").strip()
UPLOAD_MAX_FILE_SIZE_MB = int(os.getenv("UPLOAD_MAX_FILE_SIZE_MB", "25"))
UPLOAD_MAX_FILE_SIZE_BYTES = UPLOAD_MAX_FILE_SIZE_MB * 1024 * 1024

WATCH_DIR = Path(os.getenv("WATCH_DIR", "/root/autodl-tmp/input_images")).resolve()
PIPELINE_JOB_ROOT = Path(os.getenv("PIPELINE_JOB_ROOT", "/root/autodl-tmp/pipeline_jobs")).resolve()
SCENE_DATA_ROOT = Path(os.getenv("SCENE_DATA_ROOT", "/root/autodl-tmp/gs_train/scenes")).resolve()
TEST_PHOTO_ROOT = Path(os.getenv("TEST_PHOTO_ROOT", str(ROOT_DIR / "test_photo_sets"))).resolve()

POINTCLOUD_ROOTS = parse_pointcloud_roots(
    os.getenv("POINTCLOUD_ROOTS", ""),
    DEFAULT_POINTCLOUD_ROOTS,
)

DEFAULT_CONFIG: Dict[str, str] = {
    "MIN_IMG_COUNT": "60",
    "STABLE_POLLS": "3",
    "POLL_INTERVAL_SEC": "4",
    "RETRY_INTERVAL_SEC": "15",
    "SPANN3R_KF_EVERY": "6",
    "SPANN3R_CONF_THRESH": "0.015",
    "SPANN3R_VOXEL_SIZE": "0.008",
    "SPANN3R_RESOLUTION": "224",
    "TRAIN_SPLIT_FRACTION": "0.95",
    "NS_MAX_NUM_ITERATIONS": "1000",
    "NS_STEPS_PER_SAVE": "1000",
    "NS_QUIT_ON_TRAIN_COMPLETION": "true",
    "NS_TRAIN_EXTRA_ARGS": "",
    "NS_OUTPUT_ROOT": str(ROOT_DIR / "outputs"),
    "NS_EXPORT_AFTER_TRAIN": "true",
    "GAUSSIAN_EXPORT_SUBDIR": "gaussian_export",
    "GAUSSIAN_CROP_PADDING_RATIO": "0.03",
    "GAUSSIAN_REF_DISTANCE_SCALE": "4.0",
    "NS_EXPORT_EXTRA_ARGS": "",
    "UPLOAD_PORT": "6006",
    "VIEWER_PORT": "6006",
    "WATCH_DIR": str(WATCH_DIR),
    "UPLOAD_SAVE_DIR": str(WATCH_DIR),
    "PIPELINE_JOB_ROOT": str(PIPELINE_JOB_ROOT),
    "PIPELINE_JOB_ARCHIVE_ROOT": "/root/autodl-tmp/pipeline_jobs_archive",
    "PIPELINE_QUEUE_ENABLED": "true",
    "SCENE_DATA_ROOT": str(SCENE_DATA_ROOT),
    "TEST_PHOTO_ROOT": str(TEST_PHOTO_ROOT),
    "ARCHIVE_DIR": "/root/autodl-tmp/input_images_archive",
    "SCENE_NAME_PREFIX": "scene",
    "CLEAR_INPUT_AFTER_SNAPSHOT": "true",
    "MAX_SCENES_KEEP": "5",
    "MAX_PHOTO_SETS_KEEP": "5",
    "RESTART_UPLOAD_CLEANUP": "archive",
    "RESTART_UPLOAD_ARCHIVE_KEEP": "5",
    "RESTART_QUEUE_CLEANUP": "archive",
    "RESTART_QUEUE_ARCHIVE_KEEP": "5",
    "PIPELINE_STATE_FILE": str(LOG_DIR / "pipeline_state.json"),
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}

CONFIG_HELP: Dict[str, str] = {
    "MIN_IMG_COUNT": "最少照片数，达到后才会判断上传是否完成。",
    "STABLE_POLLS": "上传稳定轮数，连续 N 轮文件不再变化才会触发重建。",
    "POLL_INTERVAL_SEC": "上传监听间隔（秒），越小响应越快但轮询更频繁。",
    "RETRY_INTERVAL_SEC": "流水线失败后的自动重试等待秒数。",
    "SPANN3R_KF_EVERY": "关键帧间隔，值越大重建更快但稀疏。",
    "SPANN3R_CONF_THRESH": "点云置信度阈值，建议 0.01~0.03。",
    "SPANN3R_VOXEL_SIZE": "点云下采样体素尺寸，越大越稀疏。",
    "SPANN3R_RESOLUTION": "Spann3R 输入分辨率，常用 224。",
    "TRAIN_SPLIT_FRACTION": "训练集比例（其余用于评估）。",
    "NS_MAX_NUM_ITERATIONS": "Splatfacto 训练步数，正式展示默认 1000。",
    "NS_STEPS_PER_SAVE": "Nerfstudio checkpoint 保存间隔，默认 1000。",
    "NS_QUIT_ON_TRAIN_COMPLETION": "训练完成后是否自动退出 Viewer 并继续执行 Gaussian 导出。",
    "NS_TRAIN_EXTRA_ARGS": "透传给 ns-train 的额外参数；步数、保存间隔和 Viewer 退出由上方字段统一管理。",
    "NS_OUTPUT_ROOT": "Nerfstudio 训练输出目录（用于自动导出 Gaussian 点云）。",
    "NS_EXPORT_AFTER_TRAIN": "训练结束后是否自动执行 ns-export gaussian-splat。",
    "GAUSSIAN_EXPORT_SUBDIR": "每个场景内 Gaussian 导出目录名。",
    "GAUSSIAN_CROP_PADDING_RATIO": "按 Spann3R 输入点云边界裁切 Gaussian 点云时的边界扩展比例。",
    "GAUSSIAN_REF_DISTANCE_SCALE": "Gaussian 点云到 Spann3R 参考点云的距离过滤倍数（越小越严格）。",
    "NS_EXPORT_EXTRA_ARGS": "透传给 ns-export 的额外参数（高级调参）。",
    "UPLOAD_PORT": "上传服务端口（4090 后端模式通常为 6006）。",
    "VIEWER_PORT": "Nerfstudio Viewer 端口。",
    "WATCH_DIR": "上传照片落盘目录。",
    "UPLOAD_SAVE_DIR": "上传代理保存目录，默认与 WATCH_DIR 一致。",
    "PIPELINE_JOB_ROOT": "队列任务根目录，每个上传 session 会形成一个 job 子目录。",
    "PIPELINE_JOB_ARCHIVE_ROOT": "重启时队列任务归档目录。",
    "PIPELINE_QUEUE_ENABLED": "是否启用单卡任务队列；启用后上传会按 job/session 隔离。",
    "SCENE_DATA_ROOT": "多场景训练数据根目录（每次自动新建场景子目录）。",
    "TEST_PHOTO_ROOT": "测试照片留存目录（中期交付可复用）。",
    "ARCHIVE_DIR": "旧上传图片归档目录。",
    "SCENE_NAME_PREFIX": "新场景命名前缀。",
    "CLEAR_INPUT_AFTER_SNAPSHOT": "完成场景快照后是否清理上传目录。",
    "MAX_SCENES_KEEP": "自动保留最近场景数据集数量。",
    "MAX_PHOTO_SETS_KEEP": "自动保留最近测试照片集数量。",
    "RESTART_UPLOAD_CLEANUP": "重启后端时处理旧上传图片：archive/delete/keep。",
    "RESTART_UPLOAD_ARCHIVE_KEEP": "重启归档最多保留次数。",
    "RESTART_QUEUE_CLEANUP": "重启后端时处理旧队列任务：archive/delete/keep；默认跟随上传清理策略。",
    "RESTART_QUEUE_ARCHIVE_KEEP": "队列任务归档最多保留次数。",
    "PIPELINE_STATE_FILE": "流水线任务状态 JSON 文件路径，供前端和管理台读取。",
    "OMP_NUM_THREADS": "CPU 并行线程上限。",
    "MKL_NUM_THREADS": "MKL 线程上限。",
    "NUMEXPR_NUM_THREADS": "NumExpr 线程上限。",
}

EDITABLE_KEYS = list(DEFAULT_CONFIG.keys())

app = FastAPI(title="Spann3R Backend Dashboard")


class ConfigUpdate(BaseModel):
    values: Dict[str, str]


def require_dashboard_token(x_auth_token: str = Header(default="", alias="X-Auth-Token")) -> None:
    if not DASHBOARD_AUTH_TOKEN:
        return
    if not secrets.compare_digest(x_auth_token.strip(), DASHBOARD_AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="鉴权失败，无效 token")


def read_env_file() -> Dict[str, str]:
    return read_config_file(ENV_FILE, DEFAULT_CONFIG)


def write_env_file(values: Dict[str, str]) -> None:
    write_config_file(ENV_FILE, values, DEFAULT_CONFIG, EDITABLE_KEYS)


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def get_process_cmdline(pid: int) -> str:
    cmdline_path = Path(f"/proc/{pid}/cmdline")
    try:
        raw = cmdline_path.read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()


def is_pipeline_process(pid: int) -> bool:
    cmdline = get_process_cmdline(pid)
    if not cmdline:
        return False
    return (
        PIPELINE_MODULE in cmdline
        or str(PIPELINE_SCRIPT) in cmdline
        or "backend_4090.py" in cmdline
    )


def read_pipeline_pid() -> Optional[int]:
    if not PIPELINE_PID_FILE.exists():
        return None
    try:
        pid = int(PIPELINE_PID_FILE.read_text(encoding="utf-8").strip())
    except ValueError:
        return None
    return pid if pid > 1 else None


def get_running_pipeline_pid() -> Optional[int]:
    pid = read_pipeline_pid()
    if not pid:
        return None
    if not process_alive(pid):
        PIPELINE_PID_FILE.unlink(missing_ok=True)
        return None
    if not is_pipeline_process(pid):
        PIPELINE_PID_FILE.unlink(missing_ok=True)
        return None
    return pid


def tail_lines(path: Path, max_lines: int = 300) -> List[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return lines[-max_lines:]


def list_images(directory: Path) -> List[Path]:
    if not directory.exists():
        return []
    files = [item for item in directory.iterdir() if item.is_file() and item.suffix in IMAGE_EXTENSIONS]
    files.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)
    return files


def get_config_path(config_key: str, fallback: Path) -> Path:
    return get_config_path_from_values(read_env_file(), config_key, fallback)


def get_config_bool(config_key: str, default: bool) -> bool:
    return get_config_bool_from_values(read_env_file(), config_key, default)


def read_pipeline_state() -> Dict[str, object]:
    return STATE_STORE.read()


def normalize_state_phase(state: Dict[str, object], running: bool) -> str:
    phase = str(state.get("phase") or "idle")
    status = str(state.get("status") or "")
    if status == "running" and not running and phase not in {"completed", "failed", "stopped", "idle"}:
        return "stopped"
    return phase


def active_job_from_state(state: Dict[str, object], running: bool) -> Optional[Dict[str, object]]:
    if not state:
        return None
    job_id = str(state.get("job_id") or "")
    scene_name = str(state.get("scene_name") or "")
    if not job_id and not scene_name:
        return None
    return {
        "id": job_id or scene_name,
        "scene_name": scene_name,
        "phase": normalize_state_phase(state, running),
        "status": state.get("status") or ("running" if running else "idle"),
        "started_at": state.get("started_at") or "",
        "updated_at": state.get("updated_at") or "",
    }


def merge_state_progress(
    state: Dict[str, object],
    log_progress: Dict[str, Optional[str]],
    running: bool,
) -> Dict[str, object]:
    state_copy = dict(state)
    phase = normalize_state_phase(state_copy, running)
    if phase != state_copy.get("phase"):
        state_copy["phase"] = phase
        state_copy["status"] = "stopped"
        state_copy["message"] = "流水线进程已退出，状态标记为已停止"

    metrics = state_copy.get("metrics") if isinstance(state_copy.get("metrics"), dict) else {}
    progress: Dict[str, object] = dict(metrics)
    for key, value in log_progress.items():
        if value not in (None, ""):
            progress[key] = value

    scene_name = str(state_copy.get("scene_name") or progress.get("scene_name") or read_latest_scene())
    state_for_sections = dict(state_copy)
    state_for_sections["metrics"] = progress

    progress.update(
        {
            "job_id": state_copy.get("job_id") or scene_name,
            "scene_name": scene_name,
            "phase": phase,
            "stage": phase,
            "status": state_copy.get("status") or ("running" if running else "idle"),
            "message": state_copy.get("message") or "",
            "error": state_copy.get("error") or "",
            "started_at": state_copy.get("started_at") or "",
            "updated_at": state_copy.get("updated_at") or "",
            "completed_at": state_copy.get("completed_at") or "",
            "paths": state_copy.get("paths") or {},
            "artifacts": state_copy.get("artifacts") or {},
            "sections": build_sections(state_for_sections),
        }
    )
    return progress


def under_allowed_roots(path: Path) -> bool:
    return is_under_allowed_roots(path, POINTCLOUD_ROOTS)


def infer_pointcloud_variant(file_path: Path) -> str:
    return infer_pointcloud_variant_for_path(file_path)


def discover_pointclouds() -> List[Dict[str, str]]:
    return discover_pointcloud_items(POINTCLOUD_ROOTS)


def pick_preferred_pointcloud(
    items: List[Dict[str, str]],
    prefer: str = "gaussian",
    strict: bool = False,
) -> Optional[Dict[str, str]]:
    return pick_preferred_pointcloud_item(
        items,
        prefer=prefer,
        strict=strict,
        latest_scene=read_latest_scene(),
    )


def index_by_id() -> Dict[str, Path]:
    return index_pointclouds_by_id(discover_pointclouds())


def make_zip_response(items: List[Dict[str, str]], archive_name: str) -> FileResponse:
    if not items:
        raise HTTPException(status_code=404, detail="未找到可打包点云")

    tmp_path = write_pointcloud_zip(items, POINTCLOUD_ROOTS)

    return FileResponse(
        tmp_path,
        filename=archive_name,
        media_type="application/zip",
        background=BackgroundTask(lambda: tmp_path.unlink(missing_ok=True)),
    )


def find_scene_gaussian_files(scene_name: str) -> Dict[str, str]:
    return find_scene_gaussian_files_for_items(scene_name, discover_pointclouds())


def discover_uploaded_images(limit: int = 200) -> List[Dict[str, str]]:
    watch_dir = get_config_path("WATCH_DIR", WATCH_DIR)
    payload: List[Dict[str, str]] = []
    for image_path in list_images(watch_dir)[:limit]:
        stat = image_path.stat()
        payload.append(
            {
                "name": image_path.name,
                "size_bytes": str(stat.st_size),
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "path": str(image_path),
            }
        )
    return payload


def discover_upload_archives(limit: int = 20) -> List[Dict[str, str]]:
    archive_root = get_config_path("ARCHIVE_DIR", Path("/root/autodl-tmp/input_images_archive"))
    return discover_archive_dirs(archive_root, limit=limit)


def discover_queue_archives(limit: int = 20) -> List[Dict[str, str]]:
    archive_root = get_config_path("PIPELINE_JOB_ARCHIVE_ROOT", Path("/root/autodl-tmp/pipeline_jobs_archive"))
    return discover_archive_dirs(archive_root, limit=limit)


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
                "mtime": datetime.fromtimestamp(archive_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return payload


def discover_photo_scenes(limit: int = 200) -> List[Dict[str, str]]:
    test_photo_root = get_config_path("TEST_PHOTO_ROOT", TEST_PHOTO_ROOT)
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
                "mtime": datetime.fromtimestamp(scene_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return payload


def discover_scene_datasets(limit: int = 200) -> List[Dict[str, str]]:
    scene_data_root = get_config_path("SCENE_DATA_ROOT", SCENE_DATA_ROOT)
    if not scene_data_root.exists():
        return []
    candidates = [item for item in scene_data_root.iterdir() if item.is_dir()]
    candidates.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)

    payload: List[Dict[str, str]] = []
    for scene_dir in candidates[:limit]:
        image_dir = scene_dir / "images"
        image_count = len([item for item in image_dir.iterdir() if item.is_file() and item.suffix in IMAGE_EXTENSIONS]) if image_dir.exists() else 0
        ply_files = list(scene_dir.glob("*.ply"))
        payload.append(
            {
                "scene": scene_dir.name,
                "image_count": str(image_count),
                "pointcloud_count": str(len(ply_files)),
                "has_transforms": str((scene_dir / "transforms.json").exists()),
                "path": str(scene_dir),
                "mtime": datetime.fromtimestamp(scene_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return payload


def read_latest_scene() -> str:
    scene_data_root = get_config_path("SCENE_DATA_ROOT", SCENE_DATA_ROOT)
    marker = scene_data_root / "LATEST_SCENE.txt"
    if not marker.exists():
        return ""
    return marker.read_text(encoding="utf-8").strip()


def clear_uploaded_images() -> int:
    watch_dir = get_config_path("WATCH_DIR", WATCH_DIR)
    deleted = 0
    for image_path in list_images(watch_dir):
        image_path.unlink(missing_ok=True)
        deleted += 1
    for part_path in watch_dir.glob("*.part") if watch_dir.exists() else []:
        part_path.unlink(missing_ok=True)
        deleted += 1
    manifest = watch_dir / "_upload_manifest.jsonl"
    if manifest.exists():
        manifest.unlink(missing_ok=True)
        deleted += 1
    return deleted


def clear_upload_jobs() -> int:
    queue_root = get_config_path("PIPELINE_JOB_ROOT", PIPELINE_JOB_ROOT)
    if not queue_root.exists():
        return 0
    deleted = 0
    for job in list_jobs(queue_root, limit=1000):
        status = str(job.get("status") or "")
        if status in {"running"}:
            continue
        path = queue_root / sanitize_job_id(str(job.get("id") or job.get("job_id") or ""))
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            deleted += 1
    return deleted


def validate_upload_token(form_token: str, header_token: str) -> None:
    if not UPLOAD_AUTH_TOKEN:
        return
    token = form_token or header_token
    if not secrets.compare_digest(token.strip(), UPLOAD_AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="上传鉴权失败，无效 token")


def validate_upload_extension(filename: str) -> str:
    try:
        return validate_upload_suffix(filename)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None


def current_phase_for_upload_gate() -> str:
    running = bool(get_running_pipeline_pid())
    state = read_pipeline_state()
    if state:
        return normalize_state_phase(state, running)
    logs = extract_current_run_logs(tail_lines(PIPELINE_LOG_FILE, 1200))
    progress = parse_progress(logs)
    phase_info = build_phase_status(logs, running, progress)
    return str(phase_info.get("phase") or "unknown")


def upload_stats_payload() -> Dict[str, object]:
    watch_dir = get_config_path("WATCH_DIR", WATCH_DIR)
    queue_enabled = get_config_bool("PIPELINE_QUEUE_ENABLED", True)
    queue_root = get_config_path("PIPELINE_JOB_ROOT", PIPELINE_JOB_ROOT)
    images = list_images(watch_dir)
    total_bytes = sum(item.stat().st_size for item in images)
    phase = current_phase_for_upload_gate()
    state = read_pipeline_state()
    return {
        "status": "ok",
        "phase": phase,
        "allow_upload": queue_enabled or can_upload_by_phase(phase),
        "queue_enabled": queue_enabled,
        "queue": summarize_jobs(queue_root) if queue_enabled else {"count": 0, "queued": 0},
        "uploaded_files": len(images),
        "uploaded_bytes": total_bytes,
        "save_dir": str(queue_root if queue_enabled else watch_dir),
        "legacy_save_dir": str(watch_dir),
        "max_file_size_mb": UPLOAD_MAX_FILE_SIZE_MB,
        "active_job": active_job_from_state(state, bool(get_running_pipeline_pid())),
    }


async def save_uploaded_frame(
    frame_file: UploadFile,
    form_token: str,
    header_token: str,
    frame_index: str = "",
    session_id: str = "",
) -> Dict[str, object]:
    phase = current_phase_for_upload_gate()
    queue_enabled = get_config_bool("PIPELINE_QUEUE_ENABLED", True)
    if not queue_enabled and not can_upload_by_phase(phase):
        raise HTTPException(status_code=409, detail=f"当前阶段不可上传：{phase}")

    validate_upload_token(form_token, header_token)
    suffix = validate_upload_extension(frame_file.filename or "")

    queue_root = get_config_path("PIPELINE_JOB_ROOT", PIPELINE_JOB_ROOT)
    watch_dir = get_config_path("WATCH_DIR", WATCH_DIR)
    safe_session, save_dir = resolve_upload_destination(
        queue_enabled,
        queue_root,
        watch_dir,
        session_id,
    )
    save_dir.mkdir(parents=True, exist_ok=True)

    filename = build_upload_filename(safe_session, frame_index, suffix)
    save_path = save_dir / filename

    total_bytes = 0
    try:
        with save_path.open("wb") as handle:
            while True:
                chunk = await frame_file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > UPLOAD_MAX_FILE_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过大小限制 {UPLOAD_MAX_FILE_SIZE_MB}MB",
                    )
                handle.write(chunk)
    except HTTPException:
        save_path.unlink(missing_ok=True)
        raise
    except Exception as error:
        save_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"文件保存失败: {error}")
    finally:
        await frame_file.close()

    if queue_enabled:
        job = record_uploaded_frame(
            queue_root,
            safe_session,
            filename=filename,
            size_bytes=total_bytes,
            frame_index=frame_index,
            source_name=frame_file.filename or "",
        )
    else:
        job = {}

    manifest = save_dir / "_upload_manifest.jsonl"
    manifest_row = {
        "filename": filename,
        "bytes": total_bytes,
        "phase": phase,
        "job_id": safe_session if queue_enabled else "",
        "frame_index": frame_index,
        "session_id": session_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    with manifest.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest_row, ensure_ascii=False) + "\n")

    return {
        "code": 200,
        "ok": True,
        "msg": "上传成功",
        "filename": filename,
        "bytes": total_bytes,
        "phase": phase,
        "job_id": safe_session if queue_enabled else "",
        "queue_enabled": queue_enabled,
        "job": job,
    }


def clear_all_pointclouds() -> int:
    deleted = 0
    for root in POINTCLOUD_ROOTS:
        if not root.exists():
            continue
        for pointcloud in root.rglob("*.ply"):
            if under_allowed_roots(pointcloud):
                pointcloud.unlink(missing_ok=True)
                deleted += 1
    return deleted


def start_pipeline() -> int:
    pid = get_running_pipeline_pid()
    if pid:
        return pid

    if not PIPELINE_SCRIPT.exists():
        raise HTTPException(status_code=500, detail=f"脚本不存在: {PIPELINE_SCRIPT}")

    with PIPELINE_LOG_FILE.open("a", encoding="utf-8") as log_file:
        log_file.write(f"\n===== START {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")

    log_stream = PIPELINE_LOG_FILE.open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            [sys.executable, "-u", "-m", PIPELINE_MODULE],
            cwd=str(ROOT_DIR),
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_stream.close()
    PIPELINE_PID_FILE.write_text(str(process.pid), encoding="utf-8")
    STATE_STORE.start_job(
        f"manual_{time.strftime('%Y%m%d_%H%M%S')}",
        phase="input",
        message="流程已启动，等待上传稳定",
        paths={"watch_dir": str(get_config_path("WATCH_DIR", WATCH_DIR))},
    )
    return process.pid


def terminate_pipeline_tree(pid: int, sig: int) -> None:
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, sig)
        return
    except (OSError, ProcessLookupError):
        pass
    try:
        os.kill(pid, sig)
    except OSError:
        pass


def stop_pipeline() -> bool:
    pid = get_running_pipeline_pid()
    if not pid:
        PIPELINE_PID_FILE.unlink(missing_ok=True)
        state = read_pipeline_state()
        if state.get("status") == "running":
            STATE_STORE.stop("流程未运行，状态已标记为停止")
        return False

    terminate_pipeline_tree(pid, signal.SIGTERM)
    for _ in range(30):
        if not process_alive(pid):
            PIPELINE_PID_FILE.unlink(missing_ok=True)
            STATE_STORE.stop("用户停止训练")
            return True
        time.sleep(0.2)

    terminate_pipeline_tree(pid, signal.SIGKILL)
    PIPELINE_PID_FILE.unlink(missing_ok=True)
    STATE_STORE.stop("用户强制停止训练")
    return True


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    editable_keys_json = json.dumps(EDITABLE_KEYS, ensure_ascii=False)
    config_help_json = json.dumps(CONFIG_HELP, ensure_ascii=False)
    page = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Spann3R 后端管理台</title>
  <style>
    :root {
      --bg: #0b1020;
      --card: #11192c;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --line: #24324c;
      --accent: #38bdf8;
      --accent-soft: #0f2740;
      --good: #22c55e;
      --warn: #f59e0b;
      --danger: #ef4444;
      --term-bg: #05080f;
      --term-fg: #a7f3d0;
      --term-line: #1f2937;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: radial-gradient(1200px 600px at 90% -20%, #1e3a8a33 0%, transparent 50%), var(--bg); color: var(--text); font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif; }
    .wrap { max-width: 1280px; margin: 0 auto; padding: 20px; }
    .hero { background: linear-gradient(120deg, #0f172a 0%, #1d4ed8 100%); color: #fff; border: 1px solid #2d4f95; border-radius: 16px; padding: 18px 20px; margin-bottom: 16px; }
    .hero h1 { margin: 0 0 8px 0; font-size: 26px; }
    .hero p { margin: 0; opacity: 0.95; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .card { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 14px; box-shadow: 0 8px 28px rgba(0, 0, 0, 0.35); }
    .card h2 { margin: 0 0 10px 0; font-size: 18px; }
    .muted { color: var(--muted); font-size: 13px; }
    .line { margin: 6px 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
    .controls { margin-bottom: 8px; }
    button { border: 0; border-radius: 10px; padding: 8px 12px; font-size: 14px; cursor: pointer; margin-right: 8px; margin-bottom: 8px; }
    button:hover { filter: brightness(1.08); }
    .btn-start { background: var(--good); color: #fff; }
    .btn-stop { background: var(--danger); color: #fff; }
    .btn-save { background: #2563eb; color: #fff; }
    .btn-clean { background: #f59e0b; color: #fff; }
    .btn-danger { background: var(--danger); color: #fff; }
    .progress { width: 100%; height: 12px; background: #1f2937; border-radius: 999px; overflow: hidden; margin-top: 8px; }
    .progress > div { height: 100%; width: 0%; background: linear-gradient(90deg, #22c55e 0%, #16a34a 100%); transition: width .25s ease; }
    .mini-list { max-height: 180px; overflow: auto; margin: 8px 0 0 0; padding: 0; list-style: none; }
    .mini-list li { padding: 6px 8px; border-bottom: 1px dashed var(--line); font-size: 13px; }
    .phase-list { max-height: 130px; }
    .phase-running { color: #fbbf24; }
    .phase-done { color: #4ade80; }
    .phase-pending { color: #93c5fd; }
    .job-list { max-height: 220px; }
    .job-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    .job-main { min-width: 0; flex: 1; }
    .job-main strong { display: block; color: #fff; overflow-wrap: anywhere; }
    .job-meta { color: var(--muted); font-size: 12px; margin-top: 3px; overflow-wrap: anywhere; }
    .job-status { display: inline-block; min-width: 56px; text-align: center; border-radius: 999px; padding: 3px 7px; font-size: 12px; background: #172554; color: #bfdbfe; }
    .job-status.running { background: #1e3a8a; color: #93c5fd; }
    .job-status.completed { background: #14532d; color: #86efac; }
    .job-status.failed, .job-status.stopped { background: #7f1d1d; color: #fecaca; }
    .job-cancel { flex-shrink: 0; background: var(--danger); color: #fff; padding: 6px 9px; font-size: 12px; margin: 0; }
    .job-cancel[disabled] { cursor: not-allowed; opacity: .45; filter: grayscale(1); }
    .cfg-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; }
    .cfg-item { border: 1px solid var(--line); border-radius: 10px; padding: 8px; background: #0f1a30; }
    .cfg-item label { display: block; font-weight: 600; font-size: 13px; margin-bottom: 6px; }
    .cfg-item .help { color: var(--muted); font-size: 12px; line-height: 1.4; min-height: 30px; }
    .cfg-item input { width: 100%; margin-top: 6px; border: 1px solid #334155; border-radius: 8px; padding: 7px 8px; font-size: 13px; background: #0b1223; color: var(--text); }
    .auth-row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
    .auth-row input { border: 1px solid #334155; border-radius: 8px; padding: 7px 10px; min-width: 260px; background: #0b1223; color: var(--text); }
    pre { white-space: pre; tab-size: 4; -moz-tab-size: 4; background: var(--term-bg); color: var(--term-fg); border: 1px solid var(--term-line); border-radius: 10px; padding: 10px; min-height: 280px; max-height: 680px; overflow: auto; margin: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    a { color: #7dd3fc; text-decoration: none; }
    .single { margin-top: 14px; }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
    .chip { padding: 4px 8px; border-radius: 999px; background: var(--accent-soft); color: #bae6fd; font-size: 12px; border: 1px solid #1e3a8a; }
    @media (max-width: 920px) {
      .grid { grid-template-columns: 1fr; }
      .cfg-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>Spann3R 后端管理台（多场景预备版）</h1>
      <p>面向交付与调参：上传监控、训练进度、参数中文解释、场景资产管理</p>
    </div>

    <div class="grid">
      <div class="card">
        <h2>流程控制</h2>
        <div class="auth-row">
          <input id="authTokenInput" type="password" placeholder="管理接口 Token（可选）" />
          <button class="btn-save" onclick="saveAuthToken()">保存 Token</button>
        </div>
        <div class="controls">
          <button class="btn-start" onclick="startPipeline()">开始训练流程</button>
          <button class="btn-stop" onclick="stopPipeline()">停止流程</button>
          <button class="btn-save" onclick="exportGaussian()">导出最新Gaussian点云</button>
          <button class="btn-clean" onclick="clearUploads()">一键清空已上传照片</button>
          <button class="btn-danger" onclick="clearPointclouds()">一键清空历史点云</button>
        </div>
        <div id="statusLine" class="line"></div>
        <div id="progressLine" class="line"></div>
        <div class="progress"><div id="progressFill"></div></div>
        <div id="uploadLine" class="line"></div>
        <div id="downsampleLine" class="line"></div>
        <div id="gaussianExportLine" class="line"></div>
        <div id="phaseSummary" class="line"></div>
        <ul id="phaseList" class="mini-list phase-list"></ul>
        <div class="chips">
          <span class="chip">上传目录: <span id="watchDirChip"></span></span>
          <span class="chip">最新场景: <span id="latestSceneChip">-</span></span>
        </div>
      </div>

      <div class="card">
        <h2>上传照片监控</h2>
        <div id="uploadSummary" class="line"></div>
        <ul id="uploadList" class="mini-list"></ul>
      </div>

      <div class="card">
        <h2>任务队列</h2>
        <div id="jobSummary" class="line"></div>
        <ul id="jobList" class="mini-list job-list"></ul>
      </div>

      <div class="card">
        <h2>场景资产监控</h2>
        <div id="sceneSummary" class="line"></div>
        <ul id="sceneList" class="mini-list"></ul>
      </div>

      <div class="card">
        <h2>参数调节（含中文解释）</h2>
        <p class="muted">保存后对下一次启动生效。为避免漂移，建议优先调节置信度阈值、关键帧间隔和最小图片数。</p>
        <div id="configForm" class="cfg-grid"></div>
        <div style="margin-top:8px;"><button class="btn-save" onclick="saveConfig()">保存参数配置</button></div>
      </div>
    </div>

    <div class="card single">
      <h2>实时日志</h2>
      <pre id="logBox"></pre>
      <p class="muted" style="margin-top:8px;">
        快速入口：
        <a href="/downloads" target="_blank">点云下载页</a> |
        <a href="/files" target="_blank">点云 JSON 列表</a> |
        <a href="/healthz" target="_blank">健康检查</a>
      </p>
    </div>
  </div>

  <script>
    let configValues = {};
    const editableKeys = __EDITABLE_KEYS__;
    const configHelp = __CONFIG_HELP__;
    const AUTH_TOKEN_KEY = "dashboard_auth_token";
    const PHASE_LABELS = {
      idle: "空闲",
      input: "输入监测",
      spann3r: "Spann3R重建",
      gaussian: "Gaussian训练/导出",
      completed: "已完成",
      stopped: "已停止"
    };
    const JOB_STATUS_LABELS = {
      queued: "排队中",
      uploading: "上传中",
      ready: "待训练",
      running: "训练中",
      completed: "已完成",
      failed: "失败",
      stopped: "已取消"
    };

    function phaseLabel(phase) {
      return PHASE_LABELS[phase] || phase || "空闲";
    }

    function jobStatusLabel(status) {
      return JOB_STATUS_LABELS[status] || status || "-";
    }

    function canCancelJob(status) {
      return status === "queued" || status === "uploading" || status === "ready";
    }

    function getAuthToken() {
      return (localStorage.getItem(AUTH_TOKEN_KEY) || "").trim();
    }

    function saveAuthToken() {
      const input = document.getElementById("authTokenInput");
      const token = (input.value || "").trim();
      localStorage.setItem(AUTH_TOKEN_KEY, token);
      alert(token ? "管理 Token 已保存到浏览器本地存储" : "已清空管理 Token");
    }

    async function apiGet(url) {
      const res = await fetch(url);
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }

    async function apiPost(url, body = {}) {
      const headers = { "Content-Type": "application/json" };
      const token = getAuthToken();
      if (token) headers["X-Auth-Token"] = token;
      const res = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(body)
      });
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }

    function renderConfig() {
      const form = document.getElementById("configForm");
      form.innerHTML = "";
      editableKeys.forEach((key) => {
        const wrapper = document.createElement("div");
        wrapper.className = "cfg-item";

        const label = document.createElement("label");
        label.textContent = key;

        const help = document.createElement("div");
        help.className = "help";
        help.textContent = configHelp[key] || "";

        const input = document.createElement("input");
        input.value = configValues[key] ?? "";
        input.onchange = () => { configValues[key] = input.value; };

        wrapper.appendChild(label);
        wrapper.appendChild(help);
        wrapper.appendChild(input);
        form.appendChild(wrapper);
      });
    }

    function renderUploads(items) {
      const list = document.getElementById("uploadList");
      list.innerHTML = "";
      if (!items.length) {
        const li = document.createElement("li");
        li.textContent = "当前上传目录为空。";
        list.appendChild(li);
        return;
      }
      items.slice(0, 20).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = `${item.name} | ${item.size_bytes} bytes | ${item.mtime}`;
        list.appendChild(li);
      });
    }

    function renderJobs(data) {
      const summary = data.summary || {};
      const items = Array.isArray(data.items) ? data.items : [];
      document.getElementById("jobSummary").textContent =
        `任务: ${summary.count ?? 0} | 排队: ${summary.queued ?? 0} | 运行: ${summary.running ?? 0} | 完成: ${summary.completed ?? 0} | 失败: ${summary.failed ?? 0}`;

      const list = document.getElementById("jobList");
      list.innerHTML = "";
      if (!items.length) {
        const li = document.createElement("li");
        li.textContent = "暂无队列任务。";
        list.appendChild(li);
        return;
      }

      items.slice(0, 30).forEach((item) => {
        const status = item.status || "unknown";
        const jobId = item.id || item.job_id || "-";

        const li = document.createElement("li");
        li.className = "job-row";

        const main = document.createElement("div");
        main.className = "job-main";

        const title = document.createElement("strong");
        title.textContent = jobId;

        const meta = document.createElement("div");
        meta.className = "job-meta";
        meta.textContent = `图片 ${item.image_count ?? "-"} | 场景 ${item.scene_name || "-"} | 更新 ${item.updated_at || item.created_at || "-"}`;

        if (item.message || item.error) {
          const message = document.createElement("div");
          message.className = "job-meta";
          message.textContent = item.message || item.error;
          main.appendChild(title);
          main.appendChild(meta);
          main.appendChild(message);
        } else {
          main.appendChild(title);
          main.appendChild(meta);
        }

        const badge = document.createElement("span");
        badge.className = "job-status " + status;
        badge.textContent = jobStatusLabel(status);

        const cancelButton = document.createElement("button");
        cancelButton.className = "job-cancel";
        cancelButton.textContent = "取消";
        cancelButton.disabled = !canCancelJob(status);
        cancelButton.onclick = () => cancelJob(jobId);

        li.appendChild(main);
        li.appendChild(badge);
        li.appendChild(cancelButton);
        list.appendChild(li);
      });
    }

    function renderScenes(datasets, latestScene) {
      const list = document.getElementById("sceneList");
      list.innerHTML = "";
      if (!datasets.length) {
        const li = document.createElement("li");
        li.textContent = "尚未生成场景数据。";
        list.appendChild(li);
      } else {
        datasets.slice(0, 20).forEach((item) => {
          const li = document.createElement("li");
          li.textContent = `${item.scene} | 图片 ${item.image_count} | 点云 ${item.pointcloud_count} | transforms ${item.has_transforms}`;
          list.appendChild(li);
        });
      }
      document.getElementById("latestSceneChip").textContent = latestScene || "-";
    }

    async function refresh() {
      try {
        const [status, progress, logs, uploads, scenes, jobs] = await Promise.all([
          apiGet("/api/status"),
          apiGet("/api/progress"),
          apiGet("/api/logs?lines=500"),
          apiGet("/api/uploads/summary"),
          apiGet("/api/scenes/summary"),
          apiGet("/api/jobs")
        ]);

        document.getElementById("statusLine").textContent =
          `运行状态: ${status.running ? "运行中" : "未运行"} | PID: ${status.pid ?? "-"} | 阶段: ${phaseLabel(progress.phase)}`;

        document.getElementById("progressLine").textContent =
          `训练步数: ${progress.step ?? "-"} | Loss: ${progress.loss ?? "-"} | 最新日志: ${progress.last_line ?? "-"}`;

        const percent = Number(progress.percent ?? 0);
        const normalized = Number.isFinite(percent) ? Math.max(0, Math.min(percent, 100)) : 0;
        document.getElementById("progressFill").style.width = normalized.toFixed(2) + "%";

        document.getElementById("uploadLine").textContent =
          `上传完成照片数: ${progress.uploaded_images ?? "待检测"}`;

        document.getElementById("downsampleLine").textContent =
          progress.downsample_summary ?? "下采样成果: 待生成";

        document.getElementById("gaussianExportLine").textContent =
          progress.gaussian_summary ?? "Gaussian导出: 待训练";

        document.getElementById("phaseSummary").textContent =
          `阶段切换: 输入监测 -> Spann3R重建 -> Gaussian训练/导出 | 当前: ${phaseLabel(progress.phase)}`;

        document.getElementById("watchDirChip").textContent = uploads.watch_dir;
        document.getElementById("uploadSummary").textContent =
          `当前上传目录照片数: ${uploads.count} | 最近更新时间: ${uploads.latest_mtime ?? "-"}`;

        document.getElementById("sceneSummary").textContent =
          `场景数据集: ${scenes.dataset_count} | 测试照片集: ${scenes.photo_scene_count} | 点云文件: ${scenes.pointcloud_count}`;

        document.getElementById("logBox").textContent = logs.lines.join("\\n");

        renderUploads(uploads.items || []);
        renderJobs(jobs || {});
        renderScenes(scenes.datasets || [], scenes.latest_scene || "");
        renderPhases(progress.sections || []);
      } catch (error) {
        document.getElementById("logBox").textContent = "刷新失败: " + error;
      }
    }

    function renderPhases(sections) {
      const list = document.getElementById("phaseList");
      list.innerHTML = "";
      if (!sections.length) {
        const li = document.createElement("li");
        li.textContent = "暂无阶段信息。";
        list.appendChild(li);
        return;
      }

      sections.forEach((item) => {
        const li = document.createElement("li");
        const statusText = item.status || "pending";
        li.className = "phase-" + statusText;
        li.textContent = `${item.label} | ${statusText} | ${item.detail || "-"}`;
        list.appendChild(li);
      });
    }

    async function loadConfig() {
      const data = await apiGet("/api/config");
      configValues = data.values;
      document.getElementById("authTokenInput").value = getAuthToken();
      renderConfig();
    }

    async function saveConfig() {
      await apiPost("/api/config", { values: configValues });
      await refresh();
      alert("配置已保存，下次启动流程生效。");
    }

    async function startPipeline() {
      await apiPost("/api/pipeline/start");
      await refresh();
    }

    async function stopPipeline() {
      await apiPost("/api/pipeline/stop");
      await refresh();
    }

    async function exportGaussian() {
      const result = await apiPost("/api/gaussian/export_latest");
      alert(`Gaussian 导出完成: ${result.scene} | ${result.gaussian_file ?? "未找到输出"}`);
      await refresh();
    }

    async function clearUploads() {
      if (!confirm("确认删除旧上传照片和未运行队列任务？此操作不可恢复。")) return;
      const result = await apiPost("/api/uploads/clear");
      alert(`已删除 ${result.deleted_files ?? 0} 个上传文件，${result.deleted_jobs ?? 0} 个队列任务`);
      await refresh();
    }

    async function cancelJob(jobId) {
      if (!jobId || jobId === "-") return;
      if (!confirm(`确认取消排队任务 ${jobId}？`)) return;
      await apiPost(`/api/jobs/${encodeURIComponent(jobId)}/cancel`);
      await refresh();
    }

    async function clearPointclouds() {
      if (!confirm("确认删除所有历史点云(.ply)？此操作不可恢复。")) return;
      const result = await apiPost("/api/pointclouds/clear");
      alert(`已删除 ${result.deleted} 个点云文件`);
      await refresh();
    }

    loadConfig().then(refresh);
    setInterval(refresh, 3000);
  </script>
</body>
</html>
"""
    page = page.replace("__EDITABLE_KEYS__", editable_keys_json)
    page = page.replace("__CONFIG_HELP__", config_help_json)
    return page


@app.get("/api/status")
async def api_status():
    pid = get_running_pipeline_pid()
    state = read_pipeline_state()
    queue_root = get_config_path("PIPELINE_JOB_ROOT", PIPELINE_JOB_ROOT)
    queue_enabled = get_config_bool("PIPELINE_QUEUE_ENABLED", True)
    queue_summary = summarize_jobs(queue_root) if queue_enabled else {"queued": 0, "count": 0}
    return {
        "running": bool(pid),
        "pid": pid,
        "queue_enabled": queue_enabled,
        "queue_length": queue_summary.get("queued", 0),
        "queue": queue_summary,
        "active_job": active_job_from_state(state, bool(pid)),
    }


@app.get("/api/config")
async def api_config():
    return {"values": read_env_file()}


@app.get("/api/config_meta")
async def api_config_meta():
    return {"editable_keys": EDITABLE_KEYS, "help": CONFIG_HELP}


@app.post("/api/config")
async def api_save_config(payload: ConfigUpdate, _: None = Depends(require_dashboard_token)):
    values = read_env_file()
    for key, value in payload.values.items():
        if key in EDITABLE_KEYS:
            values[key] = str(value).strip()
    write_env_file(values)
    return {"ok": True, "values": values}


@app.get("/api/logs")
async def api_logs(lines: int = 200):
    lines = max(20, min(lines, 1000))
    return {"lines": tail_lines(PIPELINE_LOG_FILE, lines)}


@app.get("/upload-proxy/healthz")
async def upload_proxy_healthz():
    return upload_stats_payload()


@app.get("/upload-proxy/stats")
async def upload_proxy_stats():
    return upload_stats_payload()


@app.post("/upload-proxy/upload")
async def upload_proxy_upload(
    frame_file: UploadFile = File(...),
    token: str = Form(default=""),
    x_auth_token: str = Header(default="", alias="X-Auth-Token"),
    frame_index: str = Form(default=""),
    session_id: str = Form(default=""),
):
    return await save_uploaded_frame(
        frame_file=frame_file,
        form_token=token,
        header_token=x_auth_token,
        frame_index=frame_index,
        session_id=session_id,
    )


@app.get("/api/progress")
async def api_progress():
    running = bool(get_running_pipeline_pid())
    logs = extract_current_run_logs(tail_lines(PIPELINE_LOG_FILE, 1200))
    log_progress = parse_progress(logs)
    state = read_pipeline_state()
    if state:
        progress = merge_state_progress(state, log_progress, running)
    else:
        progress = log_progress
        phase_info = build_phase_status(logs, running, progress)
        progress["phase"] = phase_info["phase"]
        progress["stage"] = phase_info["phase"]
        progress["sections"] = phase_info["sections"]

    raw_points = progress.get("raw_points")
    downsampled_points = progress.get("downsampled_points")
    keep_ratio = progress.get("keep_ratio")
    if raw_points and downsampled_points:
        ratio_text = keep_ratio if keep_ratio is not None else "-"
        progress["downsample_summary"] = (
            f"下采样成果: raw={raw_points} | downsampled={downsampled_points} | 保留率={ratio_text}"
        )
    else:
        progress["downsample_summary"] = "下采样成果: 待生成"

    gaussian_raw_file = progress.get("gaussian_raw_file")
    gaussian_clipped_file = progress.get("gaussian_clipped_file")
    if not (gaussian_raw_file and gaussian_clipped_file):
        scene_name = progress.get("scene_name") or read_latest_scene()
        gaussian_files = find_scene_gaussian_files(scene_name)
        gaussian_raw_file = gaussian_raw_file or gaussian_files.get("raw")
        gaussian_clipped_file = gaussian_clipped_file or gaussian_files.get("clipped")
        progress["gaussian_raw_file"] = gaussian_raw_file
        progress["gaussian_clipped_file"] = gaussian_clipped_file
    if gaussian_raw_file and gaussian_clipped_file:
        progress["gaussian_summary"] = (
            f"Gaussian导出: raw={gaussian_raw_file} | clipped={gaussian_clipped_file}"
        )
    elif running and (progress.get("phase") == "gaussian"):
        progress["gaussian_summary"] = "Gaussian导出: 训练中，等待导出完成"
    else:
        progress["gaussian_summary"] = "Gaussian导出: 待训练"
    return progress


@app.get("/api/uploads/summary")
async def api_uploads_summary():
    watch_dir = get_config_path("WATCH_DIR", WATCH_DIR)
    queue_root = get_config_path("PIPELINE_JOB_ROOT", PIPELINE_JOB_ROOT)
    queue_enabled = get_config_bool("PIPELINE_QUEUE_ENABLED", True)
    archive_dir = get_config_path("ARCHIVE_DIR", Path("/root/autodl-tmp/input_images_archive"))
    values = read_env_file()
    all_images = list_images(watch_dir)
    items = discover_uploaded_images(limit=200)
    jobs = list_jobs(queue_root, limit=200) if queue_enabled else []
    return {
        "watch_dir": str(watch_dir),
        "queue_enabled": queue_enabled,
        "queue_root": str(queue_root),
        "queue": summarize_jobs(queue_root) if queue_enabled else {"count": 0, "queued": 0},
        "archive_dir": str(archive_dir),
        "cleanup_mode": values.get("RESTART_UPLOAD_CLEANUP", "archive"),
        "archive_keep": values.get("RESTART_UPLOAD_ARCHIVE_KEEP", "5"),
        "count": len(all_images),
        "latest_mtime": items[0]["mtime"] if items else None,
        "items": items,
        "jobs": jobs,
        "archives": discover_upload_archives(limit=20),
        "queue_archives": discover_queue_archives(limit=20),
    }


@app.post("/api/uploads/clear")
async def api_uploads_clear(_: None = Depends(require_dashboard_token)):
    deleted_files = clear_uploaded_images()
    deleted_jobs = clear_upload_jobs()
    return {"ok": True, "deleted": deleted_files + deleted_jobs, "deleted_files": deleted_files, "deleted_jobs": deleted_jobs}


@app.get("/api/scenes/summary")
async def api_scenes_summary():
    datasets = discover_scene_datasets()
    photo_scenes = discover_photo_scenes()
    pointclouds = discover_pointclouds()
    return {
        "latest_scene": read_latest_scene(),
        "dataset_count": len(datasets),
        "photo_scene_count": len(photo_scenes),
        "pointcloud_count": len(pointclouds),
        "datasets": datasets,
        "photo_scenes": photo_scenes,
    }


@app.get("/api/jobs")
async def api_jobs():
    queue_root = get_config_path("PIPELINE_JOB_ROOT", PIPELINE_JOB_ROOT)
    jobs = list_jobs(queue_root, limit=300)
    return {
        "queue_root": str(queue_root),
        "summary": summarize_jobs(queue_root),
        "items": jobs,
    }


@app.post("/api/jobs/{job_id}/cancel")
async def api_job_cancel(job_id: str, _: None = Depends(require_dashboard_token)):
    queue_root = get_config_path("PIPELINE_JOB_ROOT", PIPELINE_JOB_ROOT)
    safe_id = sanitize_job_id(job_id)
    job = next((item for item in list_jobs(queue_root, limit=1000) if item.get("id") == safe_id), None)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务不存在: {safe_id}")
    if not can_cancel_job_status(job.get("status")):
        raise HTTPException(status_code=409, detail="运行中任务请使用停止训练")
    updated = mark_job(queue_root, safe_id, "stopped", "用户取消排队任务")
    return {"ok": True, "job": updated}


@app.post("/api/pointclouds/clear")
async def api_pointclouds_clear(_: None = Depends(require_dashboard_token)):
    deleted = clear_all_pointclouds()
    return {"ok": True, "deleted": deleted}


@app.get("/api/pointclouds/summary")
async def api_pointclouds_summary():
    items = discover_pointclouds()
    return {
        "summary": summarize_pointclouds(items),
        "items": items[:300],
    }


@app.post("/api/pipeline/start")
async def api_start(_: None = Depends(require_dashboard_token)):
    pid = start_pipeline()
    return {"ok": True, "pid": pid}


@app.post("/api/pipeline/stop")
async def api_stop(_: None = Depends(require_dashboard_token)):
    stopped = stop_pipeline()
    return {"ok": True, "stopped": stopped}


@app.post("/api/gaussian/export_latest")
async def api_export_latest_gaussian(_: None = Depends(require_dashboard_token)):
    latest_scene = read_latest_scene()
    if not latest_scene:
        raise HTTPException(status_code=404, detail="未找到最新场景，请先完成一次训练入库")

    from pipeline.auto_gs import PipelineConfig, export_gaussian_artifacts

    values = read_env_file()

    def as_bool(key: str, default: bool) -> bool:
        value = values.get(key, "").strip().lower()
        if not value:
            return default
        return value in {"1", "true", "yes", "y", "on"}

    config = PipelineConfig.from_env()
    config.spann3r_root = ROOT_DIR
    config.scene_data_root = Path(values.get("SCENE_DATA_ROOT", str(SCENE_DATA_ROOT))).resolve()
    config.ns_output_root = Path(values.get("NS_OUTPUT_ROOT", str(ROOT_DIR / "outputs"))).resolve()
    config.ns_export_after_train = as_bool("NS_EXPORT_AFTER_TRAIN", True)
    config.gaussian_export_subdir = values.get("GAUSSIAN_EXPORT_SUBDIR", "gaussian_export").strip() or "gaussian_export"
    config.gaussian_crop_padding_ratio = float(values.get("GAUSSIAN_CROP_PADDING_RATIO", "0.03"))
    config.gaussian_ref_distance_scale = float(values.get("GAUSSIAN_REF_DISTANCE_SCALE", "4.0"))
    config.ns_export_extra_args = values.get("NS_EXPORT_EXTRA_ARGS", "").strip()

    scene_dir = config.scene_data_root / latest_scene
    if not scene_dir.exists():
        raise HTTPException(status_code=404, detail=f"场景目录不存在: {scene_dir}")

    STATE_STORE.update(
        phase="export",
        status="running",
        scene_name=latest_scene,
        message="手动导出 Gaussian 点云",
    )
    gaussian_artifacts = export_gaussian_artifacts(config, latest_scene, scene_dir, time.time() - 86400 * 30)
    if gaussian_artifacts:
        STATE_STORE.update(
            phase="completed",
            status="completed",
            scene_name=latest_scene,
            message="手动导出完成",
            artifacts=gaussian_artifacts,
        )

    pointclouds = discover_pointclouds()
    target = pick_preferred_pointcloud(
        [item for item in pointclouds if item["scene"] == latest_scene and item["variant"] == "gaussian"],
        prefer="gaussian",
    )
    return {
        "ok": True,
        "scene": latest_scene,
        "gaussian_file": target["path"] if target else None,
    }


@app.get("/healthz")
async def healthz():
    watch_dir = get_config_path("WATCH_DIR", WATCH_DIR)
    scene_data_root = get_config_path("SCENE_DATA_ROOT", SCENE_DATA_ROOT)
    test_photo_root = get_config_path("TEST_PHOTO_ROOT", TEST_PHOTO_ROOT)
    return {
        "status": "ok",
        "watch_dir": str(watch_dir),
        "scene_data_root": str(scene_data_root),
        "test_photo_root": str(test_photo_root),
        "pointcloud_roots": [str(root) for root in POINTCLOUD_ROOTS],
        "state_file": str(STATE_STORE.path),
        "auth_enabled": bool(DASHBOARD_AUTH_TOKEN),
    }


@app.get("/downloads", response_class=HTMLResponse)
async def downloads_page():
    files = discover_pointclouds()
    rows = []
    for item in files[:300]:
        rows.append(
            f"<tr><td>{item['scene']}</td><td>{item['variant']}</td><td>{item['name']}</td><td>{item['size_bytes']}</td>"
            f"<td>{item['mtime']}</td><td>{item['path']}</td><td><a href='{item['download_url']}'>下载</a></td></tr>"
        )
    table = "\n".join(rows) or "<tr><td colspan='7'>暂无 .ply 文件</td></tr>"
    return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>点云下载</title>
  <style>
    body {{ font-family: sans-serif; margin: 24px; background:#0b1020; color:#e5e7eb; }}
    table {{ width: 100%; border-collapse: collapse; background:#11192c; }}
    th, td {{ border: 1px solid #24324c; padding: 8px; word-break: break-all; font-size: 13px; }}
    a {{ color: #7dd3fc; }}
  </style>
</head>
<body>
  <h1>训练点云下载</h1>
  <p>可用目录: {", ".join(str(root) for root in POINTCLOUD_ROOTS)}</p>
  <p>
    <a href="/download/latest?prefer=gaussian">下载最新 Gaussian 点云</a> |
    <a href="/download/latest?prefer=downsampled">下载最新 Spann3R 下采样点云</a> |
    <a href="/files">JSON列表</a>
  </p>
  <table>
    <thead><tr><th>场景</th><th>类型</th><th>文件名</th><th>大小(bytes)</th><th>更新时间</th><th>路径</th><th>操作</th></tr></thead>
    <tbody>{table}</tbody>
  </table>
</body>
</html>
"""


@app.get("/files")
async def files():
    return {"items": discover_pointclouds()}


@app.get("/download/latest")
async def download_latest(prefer: str = "gaussian", processed: Optional[bool] = None):
    items = filter_pointclouds_by_processed(discover_pointclouds(), processed)
    if not items:
        raise HTTPException(status_code=404, detail="未找到可下载点云")
    prefer = (prefer or "gaussian").strip().lower()
    strict = prefer != "any"
    chosen = pick_preferred_pointcloud(items, prefer=prefer, strict=strict)
    if not chosen:
        if prefer == "gaussian":
            raise HTTPException(
                status_code=404,
                detail="未找到 Gaussian 训练点云（当前可能仍在训练中或尚未导出）",
            )
        raise HTTPException(status_code=404, detail=f"未找到类型为 {prefer} 的点云")
    path = Path(chosen["path"])
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.get("/download/processed/latest")
async def download_processed_latest(prefer: str = "gaussian"):
    items = filter_pointclouds_by_processed(discover_pointclouds(), True)
    if not items:
        raise HTTPException(status_code=404, detail="未找到优化后的可下载点云")
    chosen = pick_preferred_pointcloud(items, prefer=prefer, strict=False)
    if not chosen:
        raise HTTPException(status_code=404, detail=f"未找到类型为 {prefer} 的优化点云")
    path = Path(chosen["path"])
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.get("/download/scene/{scene_name}")
async def download_scene_pointcloud(
    scene_name: str,
    prefer: str = "gaussian",
    processed: Optional[bool] = None,
):
    scene_name = scene_name.strip()
    if not scene_name:
        raise HTTPException(status_code=400, detail="scene_name 不能为空")
    items = [
        item for item in filter_pointclouds_by_processed(discover_pointclouds(), processed)
        if item.get("scene") == scene_name
    ]
    if not items:
        raise HTTPException(status_code=404, detail=f"场景 {scene_name} 未找到可下载点云")
    prefer = (prefer or "gaussian").strip().lower()
    chosen = pick_preferred_pointcloud(items, prefer=prefer, strict=(prefer != "any"))
    if not chosen:
        raise HTTPException(status_code=404, detail=f"场景 {scene_name} 未找到类型为 {prefer} 的点云")
    path = Path(chosen["path"])
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.get("/download/zip")
async def download_zip(ids: str = "", variant: str = "gaussian", processed: Optional[bool] = None):
    all_items = discover_pointclouds()
    selected: List[Dict[str, str]] = []

    if ids.strip():
        wanted = {item.strip() for item in ids.split(",") if item.strip()}
        selected = [item for item in all_items if item.get("id") in wanted]
    else:
        variant_key = (variant or "gaussian").strip().lower()
        latest_scene = read_latest_scene()
        selected = [
            item for item in all_items
            if (variant_key == "any" or item.get("variant") == variant_key)
            and (not latest_scene or item.get("scene") == latest_scene)
        ]
        selected = filter_pointclouds_by_processed(selected, processed)

    archive_scene = read_latest_scene() or "pointclouds"
    archive_variant = (variant or "any").strip().lower() or "any"
    return make_zip_response(selected, f"{archive_scene}_{archive_variant}.zip")


@app.get("/download/{file_id}")
async def download_by_id(file_id: str):
    mapping = index_by_id()
    if file_id not in mapping:
        raise HTTPException(status_code=404, detail="文件不存在或已过期")
    path = mapping[file_id]
    if not path.exists() or not under_allowed_roots(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")
