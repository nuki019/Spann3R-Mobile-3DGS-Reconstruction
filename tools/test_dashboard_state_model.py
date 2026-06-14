"""Offline checks for dashboard state merge helpers."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.dashboard_state_model import (  # noqa: E402
    active_job_from_state,
    merge_state_progress,
    normalize_state_phase,
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


def test_phase_normalization() -> None:
    assert_equal(
        normalize_state_phase({"phase": "gaussian", "status": "running"}, running=True),
        "gaussian",
        "running state should keep current phase",
    )
    assert_equal(
        normalize_state_phase({"phase": "gaussian", "status": "running"}, running=False),
        "stopped",
        "exited running process should become stopped",
    )
    assert_equal(
        normalize_state_phase({"phase": "completed", "status": "completed"}, running=False),
        "completed",
        "completed state should not become stopped",
    )
    print("[OK] dashboard state phase normalization")


def test_active_job_from_state() -> None:
    assert_equal(active_job_from_state({}, running=False), None, "empty state should not expose active job")

    job = active_job_from_state(
        {
            "job_id": "job_a",
            "scene_name": "scene_a",
            "phase": "spann3r",
            "status": "running",
            "started_at": "2026-06-14T10:00:00Z",
            "updated_at": "2026-06-14T10:01:00Z",
        },
        running=False,
    )
    assert_true(job is not None, "active job should be present")
    assert_equal(job["id"], "job_a", "active job id changed")
    assert_equal(job["scene_name"], "scene_a", "active job scene changed")
    assert_equal(job["phase"], "stopped", "active job phase should reflect stopped inference")

    fallback = active_job_from_state({"scene_name": "scene_only"}, running=False)
    assert_true(fallback is not None, "scene-only state should expose active job")
    assert_equal(fallback["id"], "scene_only", "scene name should be active job fallback id")
    print("[OK] dashboard state active job")


def test_merge_state_progress() -> None:
    merged = merge_state_progress(
        {
            "job_id": "job_a",
            "scene_name": "",
            "phase": "gaussian",
            "status": "running",
            "message": "training",
            "metrics": {"uploaded_images": 60, "step": "0", "loss": ""},
            "paths": {"scene_data_dir": "/tmp/scene_a"},
            "artifacts": {"train_pointcloud": "/tmp/scene_a/input.ply"},
        },
        {"step": "120", "loss": "0.25", "scene_name": "scene_from_log", "empty": ""},
        running=True,
        latest_scene="scene_latest",
    )
    assert_equal(merged["job_id"], "job_a", "job id should come from state")
    assert_equal(merged["scene_name"], "scene_from_log", "scene name should fall back to log progress")
    assert_equal(merged["phase"], "gaussian", "phase should be preserved while running")
    assert_equal(merged["stage"], "gaussian", "stage should mirror phase")
    assert_equal(merged["uploaded_images"], 60, "state metrics should be preserved")
    assert_equal(merged["step"], "120", "log progress should override state metrics")
    assert_equal(merged["loss"], "0.25", "log progress should fill loss")
    assert_true("empty" not in merged, "empty log values should be ignored")
    assert_equal(merged["paths"]["scene_data_dir"], "/tmp/scene_a", "paths should be preserved")
    assert_true(any(item["key"] == "gaussian" for item in merged["sections"]), "sections should be built")

    stopped = merge_state_progress(
        {"phase": "spann3r", "status": "running", "metrics": {"uploaded_images": 60}},
        {},
        running=False,
        latest_scene="scene_latest",
    )
    assert_equal(stopped["phase"], "stopped", "exited incomplete flow should report stopped")
    assert_equal(stopped["status"], "stopped", "stopped merge should update status")
    assert_equal(stopped["scene_name"], "scene_latest", "latest scene fallback should be used")
    assert_true("已停止" in stopped["message"], "stopped merge should explain state change")
    print("[OK] dashboard state progress merge")


def main() -> None:
    test_phase_normalization()
    test_active_job_from_state()
    test_merge_state_progress()
    print("[OK] dashboard state model checks passed")


if __name__ == "__main__":
    main()
