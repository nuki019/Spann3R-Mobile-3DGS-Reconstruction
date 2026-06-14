"""Offline checks for backend progress log parsing and phase inference."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.progress_model import (  # noqa: E402
    build_phase_status,
    enrich_progress_response,
    extract_current_run_logs,
    parse_progress,
)


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def assert_equal(actual: object, expected: object, message: str) -> None:
    if actual != expected:
        fail(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(value: object, message: str) -> None:
    if not value:
        fail(message)


def test_extract_current_run_logs() -> None:
    logs = [
        "old line",
        "===== START old =====",
        "old run",
        "===== START current =====",
        "current run",
    ]
    assert_equal(
        extract_current_run_logs(logs),
        ["===== START current =====", "current run"],
        "current run extraction should use latest marker",
    )
    assert_equal(extract_current_run_logs(["no marker"]), ["no marker"], "logs without marker should pass through")
    print("[OK] current run log extraction")


def test_parse_progress() -> None:
    logs = [
        "上传完成确认，共 60 张",
        "Started reconstruction for scene_demo, using 60 images",
        "原始点云数量: 123456",
        "下采样点云数量: 34567 保留率=0.28",
        "Step 120 (12.0%) loss=0.1234",
        "Gaussian 点云导出完成: raw=scene_demo_gaussian_raw.ply, clipped=scene_demo_gaussian_clipped.ply",
    ]
    progress = parse_progress(logs)
    assert_equal(progress["uploaded_images"], "60", "upload count parse failed")
    assert_equal(progress["scene_name"], "scene_demo", "scene parse failed")
    assert_equal(progress["raw_points"], "123456", "raw points parse failed")
    assert_equal(progress["downsampled_points"], "34567", "downsampled points parse failed")
    assert_equal(progress["keep_ratio"], "0.28", "keep ratio parse failed")
    assert_equal(progress["step"], "120", "step parse failed")
    assert_equal(progress["percent"], "12.0", "percent parse failed")
    assert_equal(progress["loss"], "0.1234", "loss parse failed")
    assert_equal(progress["gaussian_raw_file"], "scene_demo_gaussian_raw.ply", "gaussian raw parse failed")
    assert_equal(
        progress["gaussian_clipped_file"],
        "scene_demo_gaussian_clipped.ply",
        "gaussian clipped parse failed",
    )
    assert_equal(progress["last_line"], logs[-1], "last line should be preserved")
    print("[OK] progress parser")


def test_phase_inference() -> None:
    idle = build_phase_status([], running=False, progress={})
    assert_equal(idle["phase"], "idle", "empty non-running logs should be idle")

    input_phase = build_phase_status(["waiting"], running=True, progress={})
    assert_equal(input_phase["phase"], "input", "running without progress should be input phase")

    spann3r_logs = ["上传完成确认，共 60 张", "Started reconstruction for scene_a"]
    spann3r_progress = parse_progress(spann3r_logs)
    spann3r = build_phase_status(spann3r_logs, running=True, progress=spann3r_progress)
    assert_equal(spann3r["phase"], "spann3r", "running reconstruction should be spann3r phase")
    assert_true(any(item["key"] == "spann3r" and item["status"] == "running" for item in spann3r["sections"]), "spann3r section should run")

    gaussian_logs = spann3r_logs + ["已输出 transforms.json", "启动 Nerfstudio 训练", "Step 50 (5.0%) loss=0.5"]
    gaussian_progress = parse_progress(gaussian_logs)
    gaussian = build_phase_status(gaussian_logs, running=True, progress=gaussian_progress)
    assert_equal(gaussian["phase"], "gaussian", "running nerfstudio should be gaussian phase")
    assert_true(any(item["key"] == "gaussian" and item["status"] == "running" for item in gaussian["sections"]), "gaussian section should run")

    completed_logs = gaussian_logs + [
        "Gaussian 点云导出完成: raw=scene_a_gaussian_raw.ply, clipped=scene_a_gaussian_clipped.ply",
    ]
    completed_progress = parse_progress(completed_logs)
    completed = build_phase_status(completed_logs, running=False, progress=completed_progress)
    assert_equal(completed["phase"], "completed", "exported gaussian should be completed")
    assert_true(any(item["key"] == "gaussian" and item["status"] == "done" for item in completed["sections"]), "gaussian section should be done")

    stopped = build_phase_status(spann3r_logs, running=False, progress=spann3r_progress)
    assert_equal(stopped["phase"], "stopped", "uploaded but non-running incomplete flow should be stopped")
    print("[OK] phase inference")


def test_progress_response_enrichment() -> None:
    progress = {
        "raw_points": "1000",
        "downsampled_points": "250",
        "keep_ratio": "0.25",
        "phase": "completed",
    }
    enriched = enrich_progress_response(
        progress,
        running=False,
        gaussian_files={
            "raw": "scene_gaussian_raw.ply",
            "clipped": "scene_gaussian_clipped.ply",
        },
    )
    assert_equal(
        enriched["downsample_summary"],
        "下采样成果: raw=1000 | downsampled=250 | 保留率=0.25",
        "downsample summary changed",
    )
    assert_equal(enriched["gaussian_raw_file"], "scene_gaussian_raw.ply", "raw gaussian file fill changed")
    assert_equal(
        enriched["gaussian_clipped_file"],
        "scene_gaussian_clipped.ply",
        "clipped gaussian file fill changed",
    )
    assert_equal(
        enriched["gaussian_summary"],
        "Gaussian导出: raw=scene_gaussian_raw.ply | clipped=scene_gaussian_clipped.ply",
        "gaussian summary changed",
    )

    running = enrich_progress_response({"phase": "gaussian"}, running=True)
    assert_equal(running["downsample_summary"], "下采样成果: 待生成", "missing downsample summary changed")
    assert_equal(running["gaussian_summary"], "Gaussian导出: 训练中，等待导出完成", "running gaussian summary changed")

    pending = enrich_progress_response({}, running=False)
    assert_equal(pending["gaussian_summary"], "Gaussian导出: 待训练", "pending gaussian summary changed")
    print("[OK] progress response enrichment")


def main() -> None:
    test_extract_current_run_logs()
    test_parse_progress()
    test_phase_inference()
    test_progress_response_enrichment()
    print("[OK] progress model checks passed")


if __name__ == "__main__":
    main()
