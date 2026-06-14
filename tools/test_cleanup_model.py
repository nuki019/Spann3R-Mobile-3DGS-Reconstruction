"""Offline checks for dashboard cleanup helpers."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.cleanup_model import clear_non_running_jobs, clear_uploaded_inputs  # noqa: E402


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def assert_equal(actual: object, expected: object, message: str) -> None:
    if actual != expected:
        fail(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(value: object, message: str) -> None:
    if not value:
        fail(message)


def test_clear_uploaded_inputs() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        watch_dir = Path(tmp_dir)
        (watch_dir / "frame.jpg").write_bytes(b"jpg")
        (watch_dir / "frame.PNG").write_bytes(b"png")
        (watch_dir / "upload.part").write_bytes(b"part")
        (watch_dir / "_upload_manifest.jsonl").write_text("{}\n", encoding="utf-8")
        (watch_dir / "keep.txt").write_text("keep", encoding="utf-8")

        deleted = clear_uploaded_inputs(watch_dir)
        assert_equal(deleted, 4, "cleanup should count images, part files, and manifest")
        assert_true(not (watch_dir / "frame.jpg").exists(), "jpg should be removed")
        assert_true(not (watch_dir / "frame.PNG").exists(), "png should be removed")
        assert_true(not (watch_dir / "upload.part").exists(), "part file should be removed")
        assert_true(not (watch_dir / "_upload_manifest.jsonl").exists(), "manifest should be removed")
        assert_true((watch_dir / "keep.txt").exists(), "unrelated files should be kept")
    print("[OK] cleanup uploaded inputs")


def test_clear_non_running_jobs() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        queue_root = Path(tmp_dir)
        for job_id in ["queued", "running", "completed", "unsafe_name"]:
            (queue_root / job_id / "images").mkdir(parents=True)
            (queue_root / job_id / "images" / "frame.jpg").write_bytes(b"jpg")

        deleted = clear_non_running_jobs(
            queue_root,
            [
                {"id": "queued", "status": "queued"},
                {"id": "running", "status": "running"},
                {"id": "completed", "status": "completed"},
                {"id": "../../unsafe name", "status": "failed"},
            ],
        )
        assert_equal(deleted, 3, "cleanup should delete non-running job dirs")
        assert_true(not (queue_root / "queued").exists(), "queued job should be deleted")
        assert_true((queue_root / "running").exists(), "running job must be protected")
        assert_true(not (queue_root / "completed").exists(), "completed job should be deleted")
        assert_true(not (queue_root / "unsafe_name").exists(), "job id should be sanitized before deletion")
    print("[OK] cleanup non-running jobs")


def main() -> None:
    test_clear_uploaded_inputs()
    test_clear_non_running_jobs()
    print("[OK] cleanup model checks passed")


if __name__ == "__main__":
    main()
