"""Self-contained tests for pipeline queue and state models."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pipeline.job_queue import (  # noqa: E402
    build_image_fingerprint,
    build_cancel_job_decision,
    job_dir,
    job_images_dir,
    list_images,
    list_jobs,
    list_runnable_jobs,
    mark_job,
    mark_queue_job_completed,
    mark_queue_job_failed,
    queue_job_id,
    read_job,
    record_uploaded_frame,
    sanitize_job_id,
    summarize_jobs,
)
from pipeline.job_policy import (  # noqa: E402
    can_cancel_job_status,
    can_upload_by_phase,
    is_runnable_job_status,
    next_status_after_upload,
    summarize_job_statuses,
)
from pipeline.task_state import PipelineStateStore  # noqa: E402


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def assert_equal(actual: object, expected: object, message: str) -> None:
    if actual != expected:
        fail(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(value: object, message: str) -> None:
    if not value:
        fail(message)


def test_job_policy_model() -> None:
    assert_true(is_runnable_job_status("queued"), "queued jobs should be runnable")
    assert_true(is_runnable_job_status("uploading"), "uploading jobs should be runnable")
    assert_true(is_runnable_job_status("ready"), "ready jobs should be runnable")
    assert_true(not is_runnable_job_status("running"), "running jobs must not be runnable")

    assert_true(can_cancel_job_status("queued"), "queued jobs should be cancellable")
    assert_true(can_cancel_job_status("uploading"), "uploading jobs should be cancellable")
    assert_true(can_cancel_job_status("ready"), "ready jobs should be cancellable")
    assert_true(not can_cancel_job_status("running"), "running jobs must use pipeline stop")
    assert_true(not can_cancel_job_status("completed"), "completed jobs must not be cancellable")
    assert_true(not can_cancel_job_status("failed"), "failed jobs must not be cancellable")
    assert_true(not can_cancel_job_status("stopped"), "stopped jobs must not be cancellable")

    assert_equal(next_status_after_upload(""), "queued", "new uploads should queue jobs")
    assert_equal(next_status_after_upload("ready"), "queued", "ready uploads should refresh as queued")
    assert_equal(next_status_after_upload("running"), "running", "running jobs must stay running after late upload")
    assert_equal(next_status_after_upload("completed"), "completed", "completed jobs must not reopen after upload")

    for phase in ["idle", "input", "upload", "stopped", "unknown"]:
        assert_true(can_upload_by_phase(phase), f"{phase} should allow legacy upload")
    for phase in ["spann3r", "gaussian", "export", "completed", "failed"]:
        assert_true(not can_upload_by_phase(phase), f"{phase} should block legacy upload")

    summary = summarize_job_statuses(
        [
            {"status": "queued"},
            {"status": "uploading"},
            {"status": "ready"},
            {"status": "running"},
            {"status": "completed"},
            {"status": "failed"},
            {"status": "stopped"},
        ]
    )
    assert_equal(summary["queued"], 3, "summary queued bucket should include runnable waiting statuses")
    assert_equal(summary["running"], 1, "summary running count changed")
    assert_equal(summary["completed"], 1, "summary completed count changed")
    assert_equal(summary["failed"], 1, "summary failed count changed")
    assert_equal(summary["stopped"], 1, "summary stopped count changed")
    print("[OK] job policy model tests")


def test_job_queue_model() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        queue_root = Path(tmp_dir)
        job_id = sanitize_job_id("wx/session 01")
        assert_equal(job_id, "wx_session_01", "sanitize_job_id should normalize session ids")
        assert_equal(
            sanitize_job_id("../../wx session 01///"),
            "wx_session_01",
            "sanitize_job_id should remove path traversal characters",
        )
        assert_true(
            len(sanitize_job_id("x" * 120)) <= 80,
            "sanitize_job_id should cap long session ids",
        )
        assert_true(
            sanitize_job_id("!!!").startswith("job_"),
            "sanitize_job_id should generate fallback ids for empty input",
        )

        images_dir = job_images_dir(queue_root, job_id)
        images_dir.mkdir(parents=True)
        (images_dir / "frame_000.jpg").write_bytes(b"fake-jpeg")
        (images_dir / "notes.txt").write_text("ignored", encoding="utf-8")
        os.utime(images_dir / "frame_000.jpg", ns=(2_000_000_000, 2_000_000_000))
        (images_dir / "frame_older.PNG").write_bytes(b"older")
        os.utime(images_dir / "frame_older.PNG", ns=(1_000_000_000, 1_000_000_000))

        listed_images = list_images(images_dir)
        assert_equal(
            [path.name for path in listed_images],
            ["frame_older.PNG", "frame_000.jpg"],
            "queue image listing should match storage ordering and extension rules",
        )
        fingerprint = build_image_fingerprint(listed_images)
        assert_equal(fingerprint[0][0], "frame_older.PNG", "queue fingerprint should use image names")
        assert_equal(fingerprint[0][1], 5, "queue fingerprint should use image sizes")

        queued = record_uploaded_frame(
            queue_root,
            job_id,
            filename="frame_000.jpg",
            size_bytes=9,
            frame_index="0",
            source_name="frame.jpg",
        )
        assert_equal(queued["status"], "queued", "uploaded frame should create a queued job")
        assert_equal(queued["image_count"], 2, "queue image count should include only images")
        assert_true(Path(str(queued["manifest"])).exists(), "upload manifest should exist")

        manifest_lines = Path(str(queued["manifest"])).read_text(encoding="utf-8").splitlines()
        assert_equal(len(manifest_lines), 1, "upload manifest should contain one row")
        manifest_row = json.loads(manifest_lines[0])
        assert_equal(manifest_row["frame_index"], "0", "manifest should preserve frame index")

        assert_equal(len(list_runnable_jobs(queue_root)), 1, "queued job should be runnable")
        assert_equal(summarize_jobs(queue_root)["queued"], 1, "summary should count queued jobs")
        cancel_queued = build_cancel_job_decision(list_jobs(queue_root), "wx/session 01")
        assert_equal(cancel_queued["job_id"], job_id, "cancel decision should sanitize job id")
        assert_true(cancel_queued["exists"], "queued job should exist for cancellation")
        assert_true(cancel_queued["cancellable"], "queued job should be cancellable")

        running = mark_job(queue_root, job_id, "running", "training started", scene_name="scene_a")
        assert_equal(running["status"], "running", "mark_job should update status")
        assert_equal(read_job(queue_root, job_id)["scene_name"], "scene_a", "job should store scene name")
        cancel_running = build_cancel_job_decision(list_jobs(queue_root), job_id)
        assert_true(cancel_running["exists"], "running job should exist for cancellation decision")
        assert_true(not cancel_running["cancellable"], "running job should not be cancellable via queue cancel")
        assert_equal(cancel_running["status"], "running", "cancel decision should preserve status")

        (images_dir / "frame_001.jpg").write_bytes(b"late-jpeg")
        late = record_uploaded_frame(
            queue_root,
            job_id,
            filename="frame_001.jpg",
            size_bytes=9,
            frame_index="1",
            source_name="frame.jpg",
        )
        assert_equal(late["status"], "running", "late upload must not reset running job to queued")
        assert_equal(late["image_count"], 3, "late upload should refresh image count")
        assert_equal(len(list_runnable_jobs(queue_root)), 0, "running job must not be runnable again")
        assert_equal(summarize_jobs(queue_root)["running"], 1, "summary should count running jobs")
        manifest_lines = Path(str(late["manifest"])).read_text(encoding="utf-8").splitlines()
        assert_equal(len(manifest_lines), 2, "manifest should append late upload rows")

        completed = mark_job(
            queue_root,
            job_id,
            "completed",
            "done",
            extra={"artifacts": {"gaussian": "/tmp/scene_a_gaussian.ply"}},
        )
        assert_equal(completed["status"], "completed", "completed job should be marked completed")
        assert_true(completed.get("completed_at"), "completed job should have completed_at")
        assert_equal(summarize_jobs(queue_root)["completed"], 1, "summary should count completed jobs")

        assert_equal(queue_job_id({"job_id": "wx/session 01"}, "fallback"), job_id, "queue job id should use job_id")
        assert_equal(queue_job_id({}, "scene/fallback"), "scene_fallback", "queue job id should use fallback")

        completed_by_helper = mark_queue_job_completed(
            queue_root,
            {"id": job_id},
            "scene_a",
            {"gaussian": "/tmp/scene_a_gaussian.ply"},
            Path("/tmp/scene_a"),
        )
        assert_equal(completed_by_helper["status"], "completed", "completed helper status changed")
        assert_equal(completed_by_helper["scene_name"], "scene_a", "completed helper scene changed")
        assert_equal(
            completed_by_helper["artifacts"],
            {"gaussian": "/tmp/scene_a_gaussian.ply"},
            "completed helper artifacts changed",
        )
        assert_equal(completed_by_helper["scene_data_dir"], str(Path("/tmp/scene_a")), "completed helper data dir changed")

        (images_dir / "frame_002.jpg").write_bytes(b"post-complete")
        post_complete = record_uploaded_frame(
            queue_root,
            job_id,
            filename="frame_002.jpg",
            size_bytes=13,
            frame_index="2",
            source_name="frame.jpg",
        )
        assert_equal(
            post_complete["status"],
            "completed",
            "post-completion upload must not reopen completed jobs",
        )
        assert_equal(post_complete["image_count"], 4, "post-completion upload should refresh image count")
        manifest_lines = Path(str(post_complete["manifest"])).read_text(encoding="utf-8").splitlines()
        assert_equal(len(manifest_lines), 3, "manifest should append post-completion rows")

        other_id = sanitize_job_id("wx/session 02")
        other_images = job_images_dir(queue_root, other_id)
        other_images.mkdir(parents=True)
        (other_images / "frame.jpg").write_bytes(b"fake")
        record_uploaded_frame(queue_root, other_id, "frame.jpg", 4)
        mark_job(queue_root, other_id, "stopped", "cancelled")
        failed_by_helper = mark_queue_job_failed(queue_root, {"job_id": other_id}, RuntimeError("synthetic failure"))
        assert_equal(failed_by_helper["status"], "failed", "failed helper status changed")
        assert_true("synthetic failure" in failed_by_helper["error"], "failed helper error changed")
        assert_true(failed_by_helper.get("completed_at"), "failed helper should set completed_at")
        runnable_ids = {str(job.get("id")) for job in list_runnable_jobs(queue_root)}
        assert_true(other_id not in runnable_ids, "stopped job must not be runnable")
        summary = summarize_jobs(queue_root)
        assert_equal(summary["failed"], 1, "summary should count failed jobs separately")
        cancel_missing = build_cancel_job_decision(list_jobs(queue_root), "missing/job")
        assert_equal(cancel_missing["job_id"], "missing_job", "missing cancel decision should sanitize id")
        assert_true(not cancel_missing["exists"], "missing job should not exist")
        assert_true(not cancel_missing["cancellable"], "missing job must not be cancellable")

        jobs = list_jobs(queue_root)
        assert_true(all(job_dir(queue_root, str(job["id"])).exists() for job in jobs), "job dirs should exist")
        bad_job = job_dir(queue_root, "bad-json")
        bad_job.mkdir(parents=True)
        (bad_job / "status.json").write_text("{not json", encoding="utf-8")
        listed_ids = {str(job.get("id")) for job in list_jobs(queue_root)}
        assert_true("bad-json" not in listed_ids, "corrupted jobs should be skipped")
    print("[OK] job queue model tests")


def test_pipeline_state_model() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_path = Path(tmp_dir) / "pipeline_state.json"
        store = PipelineStateStore(state_path)

        started = store.start_job(
            "job_1",
            phase="input",
            message="waiting",
            paths={"queue_job_id": "job_1"},
            metrics={"uploaded_images": 5, "stable_rounds": 1, "stable_polls": 3, "min_img_count": 60},
        )
        assert_equal(started["schema_version"], 1, "state should include schema version")
        assert_equal(started["phase_label"], "检测上传", "state should include phase label")
        assert_equal(len(started["sections"]), 4, "state should include four UI sections")

        gaussian = store.update(
            phase="gaussian",
            status="running",
            scene_name="scene_a",
            metrics={"step": 10, "loss": "0.25", "percent": 1},
            artifacts={"train_pointcloud": "/tmp/init.ply"},
        )
        assert_equal(gaussian["metrics"]["uploaded_images"], 5, "metrics should merge previous values")
        assert_equal(gaussian["metrics"]["step"], 10, "metrics should store new values")
        assert_equal(gaussian["artifacts"]["train_pointcloud"], "/tmp/init.ply", "artifacts should merge")
        assert_equal(gaussian["sections"][2]["status"], "running", "gaussian section should be running")

        failed = store.fail(RuntimeError("synthetic failure"))
        assert_equal(failed["status"], "failed", "fail should mark state failed")
        assert_equal(failed["phase"], "gaussian", "fail should preserve current phase")
        assert_true("synthetic failure" in str(failed["error"]), "fail should record error text")
        assert_true(failed.get("completed_at"), "failed state should set completed_at")

        stopped = store.stop("manual stop")
        assert_equal(stopped["status"], "stopped", "stop should mark stopped")
        assert_equal(stopped["phase"], "stopped", "stop should set stopped phase")
        assert_equal(stopped["message"], "manual stop", "stop should preserve message")

        state_path.write_text("{not json", encoding="utf-8")
        assert_equal(store.read(), {}, "corrupted state file should read as empty dict")
    print("[OK] pipeline state model tests")


def main() -> None:
    test_job_policy_model()
    test_job_queue_model()
    test_pipeline_state_model()
    print("[OK] pipeline model tests passed")


if __name__ == "__main__":
    main()
