"""Pure progress parsing helpers for dashboard and frontend status."""

from __future__ import annotations

import re
from typing import Dict, List, Optional


STEP_PATTERNS = [
    re.compile(r"Step[:=\s]+(\d+)", re.IGNORECASE),
    re.compile(r"Iter(?:ation)?[:=\s]+(\d+)", re.IGNORECASE),
    re.compile(r"(?:^|\s)(\d+)\s+\(\d+(?:\.\d+)?%\)"),
]
LOSS_PATTERN = re.compile(r"loss[:=\s]+([0-9]*\.?[0-9]+)", re.IGNORECASE)
PERCENT_PATTERN = re.compile(r"\((\d+(?:\.\d+)?)%\)")
UPLOAD_DONE_PATTERN = re.compile(r"上传完成确认[，,]\s*共\s*(\d+)\s*张")
RAW_POINTS_PATTERN = re.compile(r"原始点云数量:\s*(\d+)")
DOWNSAMPLED_POINTS_PATTERN = re.compile(r"下采样点云数量:\s*(\d+).*保留率=([0-9]*\.?[0-9]+)")
SPANN3R_SCENE_PATTERN = re.compile(r"Started reconstruction for\s+([^\s,]+)")
GAUSSIAN_EXPORT_PATTERN = re.compile(r"Gaussian\s*点云导出完成:\s*raw=([^,]+),\s*clipped=([^\s]+)")


def extract_current_run_logs(logs: List[str]) -> List[str]:
    for index in range(len(logs) - 1, -1, -1):
        if logs[index].startswith("===== START "):
            return logs[index:]
    return logs


def parse_progress(logs: List[str]) -> Dict[str, Optional[str]]:
    step_value: Optional[str] = None
    loss_value: Optional[str] = None
    percent_value: Optional[str] = None
    uploaded_count: Optional[str] = None
    raw_points: Optional[str] = None
    downsampled_points: Optional[str] = None
    keep_ratio: Optional[str] = None
    scene_name: Optional[str] = None
    gaussian_raw_file: Optional[str] = None
    gaussian_clipped_file: Optional[str] = None
    last_line: Optional[str] = logs[-1] if logs else None

    for line in logs:
        for pattern in STEP_PATTERNS:
            match = pattern.search(line)
            if match:
                step_value = match.group(1)
        loss_match = LOSS_PATTERN.search(line)
        if loss_match:
            loss_value = loss_match.group(1)
        percent_match = PERCENT_PATTERN.search(line)
        if percent_match:
            percent_value = percent_match.group(1)
        upload_match = UPLOAD_DONE_PATTERN.search(line)
        if upload_match:
            uploaded_count = upload_match.group(1)
        raw_match = RAW_POINTS_PATTERN.search(line)
        if raw_match:
            raw_points = raw_match.group(1)
        downsampled_match = DOWNSAMPLED_POINTS_PATTERN.search(line)
        if downsampled_match:
            downsampled_points = downsampled_match.group(1)
            keep_ratio = downsampled_match.group(2)
        scene_match = SPANN3R_SCENE_PATTERN.search(line)
        if scene_match:
            scene_name = scene_match.group(1)
        gaussian_match = GAUSSIAN_EXPORT_PATTERN.search(line)
        if gaussian_match:
            gaussian_raw_file = gaussian_match.group(1)
            gaussian_clipped_file = gaussian_match.group(2)

    return {
        "step": step_value,
        "loss": loss_value,
        "percent": percent_value,
        "uploaded_images": uploaded_count,
        "raw_points": raw_points,
        "downsampled_points": downsampled_points,
        "keep_ratio": keep_ratio,
        "scene_name": scene_name,
        "gaussian_raw_file": gaussian_raw_file,
        "gaussian_clipped_file": gaussian_clipped_file,
        "last_line": last_line,
    }


def build_phase_status(
    logs: List[str],
    running: bool,
    progress: Dict[str, Optional[str]],
) -> Dict[str, object]:
    if not logs and not running:
        return {
            "phase": "idle",
            "sections": [
                {"key": "input", "label": "输入监测", "status": "pending", "detail": "等待开始"},
                {"key": "spann3r", "label": "Spann3R 重建", "status": "pending", "detail": "等待输入完成"},
                {"key": "gaussian", "label": "Gaussian 训练", "status": "pending", "detail": "等待重建完成"},
            ],
        }

    text = "\n".join(logs)
    input_done = progress.get("uploaded_images") is not None
    spann3r_started = ("Started reconstruction for" in text) or ("阶段切换: Spann3R" in text)
    spann3r_done = ("Finished reconstruction for" in text) or ("已输出 transforms.json" in text)
    gaussian_started = (
        ("启动 Nerfstudio 训练" in text)
        or ("ns-train" in text)
        or ("阶段切换: Gaussian" in text)
    )
    gaussian_done = progress.get("gaussian_clipped_file") is not None or (not running and gaussian_started)

    input_status = "done" if input_done else ("running" if running else "pending")
    spann3r_status = (
        "done"
        if (spann3r_done or gaussian_started)
        else ("running" if running and (input_done or spann3r_started) else "pending")
    )
    gaussian_status = "done" if gaussian_done else ("running" if running and gaussian_started else "pending")

    if running:
        if gaussian_status == "running":
            phase = "gaussian"
        elif spann3r_status == "running":
            phase = "spann3r"
        else:
            phase = "input"
    else:
        if gaussian_status == "done":
            phase = "completed"
        elif input_done or spann3r_done:
            phase = "stopped"
        else:
            phase = "idle"

    sections = [
        {
            "key": "input",
            "label": "输入监测",
            "status": input_status,
            "detail": f"上传完成 {progress.get('uploaded_images')} 张" if input_done else "等待上传稳定",
        },
        {
            "key": "spann3r",
            "label": "Spann3R 重建",
            "status": spann3r_status,
            "detail": progress.get("scene_name") or "待开始",
        },
        {
            "key": "gaussian",
            "label": "Gaussian 训练/导出",
            "status": gaussian_status,
            "detail": (
                f"Step={progress.get('step') or '-'} Loss={progress.get('loss') or '-'}"
                if gaussian_started
                else "待开始"
            ),
        },
    ]
    return {"phase": phase, "sections": sections}


def enrich_progress_response(
    progress: Dict[str, object],
    running: bool,
    gaussian_files: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
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
    gaussian_files = gaussian_files or {}
    if not (gaussian_raw_file and gaussian_clipped_file):
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
