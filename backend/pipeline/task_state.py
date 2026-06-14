import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STATE_FILE = ROOT_DIR / "logs" / "pipeline_state.json"

PHASE_LABELS = {
    "idle": "空闲",
    "input": "检测上传",
    "upload": "检测上传",
    "spann3r": "Spann3R 训练",
    "gaussian": "3DGaussian 训练",
    "export": "点云导出",
    "completed": "训练完成",
    "stopped": "已停止",
    "failed": "失败",
}


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def default_state_file() -> Path:
    return Path(os.getenv("PIPELINE_STATE_FILE", str(DEFAULT_STATE_FILE))).resolve()


def _merge_dict(base: Dict[str, object], patch: Optional[Dict[str, object]]) -> Dict[str, object]:
    merged = dict(base or {})
    if patch:
        for key, value in patch.items():
            if value is not None:
                merged[key] = value
    return merged


def build_sections(state: Dict[str, object]) -> list:
    phase = str(state.get("phase") or "idle")
    status = str(state.get("status") or ("running" if phase not in {"idle", "completed"} else phase))
    metrics = state.get("metrics") if isinstance(state.get("metrics"), dict) else {}
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    error = str(state.get("error") or "")
    scene_name = str(state.get("scene_name") or "")

    uploaded = metrics.get("uploaded_images") or metrics.get("image_count") or 0
    stable_rounds = metrics.get("stable_rounds")
    min_images = metrics.get("min_img_count") or metrics.get("min_images")
    step = metrics.get("step") or "-"
    loss = metrics.get("loss") or "-"
    percent = metrics.get("percent") or "-"

    def status_for(order_phase: str) -> str:
        if status == "failed":
            return "warn" if phase == order_phase else ("done" if is_before(order_phase, phase) else "pending")
        if status == "stopped":
            return "warn" if phase == order_phase else ("done" if is_before(order_phase, phase) else "pending")
        if phase == order_phase:
            return "running"
        if phase == "completed":
            return "done"
        if phase == "export" and order_phase == "gaussian":
            return "running"
        return "done" if is_before(order_phase, phase) else "pending"

    upload_detail = f"已接收 {uploaded} 张"
    if stable_rounds is not None and min_images is not None:
        upload_detail += f"，稳定检测 {stable_rounds}/{metrics.get('stable_polls', '-')}, 阈值 {min_images} 张"

    spann3r_detail = scene_name or "等待上传稳定后开始"
    gaussian_detail = f"Step={step} Loss={loss} 进度={percent}"
    if phase == "export":
        gaussian_detail = "训练完成，正在导出点云"
    completed_detail = "完成后可查看 Viewer 与下载点云"
    if artifacts.get("gaussian_clipped"):
        completed_detail = f"优化点云: {Path(str(artifacts['gaussian_clipped'])).name}"
    if error:
        completed_detail = error

    return [
        {
            "key": "upload",
            "label": "检测上传",
            "status": status_for("input"),
            "detail": upload_detail,
        },
        {
            "key": "spann3r",
            "label": "Spann3R 训练",
            "status": status_for("spann3r"),
            "detail": spann3r_detail,
        },
        {
            "key": "gaussian",
            "label": "3DGaussian 训练",
            "status": status_for("gaussian"),
            "detail": gaussian_detail,
        },
        {
            "key": "completed",
            "label": "训练完成",
            "status": "done" if phase == "completed" else ("warn" if status in {"failed", "stopped"} else "pending"),
            "detail": completed_detail,
        },
    ]


def is_before(left: str, right: str) -> bool:
    order = ["input", "spann3r", "gaussian", "export", "completed"]
    if left == "upload":
        left = "input"
    if right == "upload":
        right = "input"
    try:
        return order.index(left) < order.index(right)
    except ValueError:
        return False


class PipelineStateStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = (path or default_state_file()).resolve()

    def read(self) -> Dict[str, object]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def write(self, state: Dict[str, object]) -> Dict[str, object]:
        payload = dict(state)
        payload["schema_version"] = 1
        payload["updated_at"] = utc_now()
        payload["phase_label"] = PHASE_LABELS.get(str(payload.get("phase") or ""), str(payload.get("phase") or ""))
        payload["sections"] = build_sections(payload)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(self.path)
        return payload

    def start_job(
        self,
        job_id: str,
        phase: str = "input",
        message: str = "",
        paths: Optional[Dict[str, object]] = None,
        metrics: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        now = utc_now()
        state = {
            "job_id": job_id,
            "scene_name": "",
            "phase": phase,
            "status": "running",
            "message": message,
            "error": "",
            "started_at": now,
            "completed_at": "",
            "paths": paths or {},
            "metrics": metrics or {},
            "artifacts": {},
        }
        return self.write(state)

    def update(
        self,
        phase: Optional[str] = None,
        status: Optional[str] = None,
        scene_name: Optional[str] = None,
        job_id: Optional[str] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
        metrics: Optional[Dict[str, object]] = None,
        paths: Optional[Dict[str, object]] = None,
        artifacts: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        state = self.read()
        if not state:
            state = {
                "job_id": job_id or "",
                "scene_name": scene_name or "",
                "phase": phase or "idle",
                "status": status or "idle",
                "started_at": utc_now(),
                "completed_at": "",
                "paths": {},
                "metrics": {},
                "artifacts": {},
                "error": "",
                "message": "",
            }

        if phase is not None:
            state["phase"] = phase
        if status is not None:
            state["status"] = status
        if scene_name is not None:
            state["scene_name"] = scene_name
        if job_id is not None:
            state["job_id"] = job_id
        if message is not None:
            state["message"] = message
        if error is not None:
            state["error"] = error
        if status in {"completed", "failed", "stopped"}:
            state["completed_at"] = utc_now()

        state["metrics"] = _merge_dict(state.get("metrics", {}), metrics)
        state["paths"] = _merge_dict(state.get("paths", {}), paths)
        state["artifacts"] = _merge_dict(state.get("artifacts", {}), artifacts)
        return self.write(state)

    def fail(self, error: Exception) -> Dict[str, object]:
        state = self.read()
        phase = str(state.get("phase") or "failed") if state else "failed"
        return self.update(status="failed", phase=phase, error=str(error), message="流水线执行失败")

    def stop(self, message: str = "流程已停止") -> Dict[str, object]:
        return self.update(status="stopped", phase="stopped", message=message)
