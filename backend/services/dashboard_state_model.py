"""Pure dashboard state merge helpers."""

from __future__ import annotations

from typing import Dict, Optional

from pipeline.task_state import build_sections


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
    latest_scene: str = "",
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

    scene_name = str(state_copy.get("scene_name") or progress.get("scene_name") or latest_scene)
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
