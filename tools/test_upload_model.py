"""Offline checks for shared upload naming and destination helpers."""

from __future__ import annotations

import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pipeline.job_queue import job_images_dir  # noqa: E402
from services.upload_model import (  # noqa: E402
    build_upload_filename,
    build_upload_manifest_row,
    build_upload_response,
    resolve_upload_destination,
    sanitize_frame_index,
    validate_upload_suffix,
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


def assert_raises_value_error(fn, message: str) -> None:
    try:
        fn()
    except ValueError:
        return
    fail(message)


def test_upload_suffix() -> None:
    assert_equal(validate_upload_suffix("frame.JPG"), ".jpg", "suffix should normalize case")
    assert_equal(validate_upload_suffix("frame.jpeg"), ".jpeg", "jpeg suffix should be accepted")
    assert_equal(validate_upload_suffix("frame.png"), ".png", "png suffix should be accepted")
    assert_raises_value_error(lambda: validate_upload_suffix("frame.gif"), "gif must be rejected")
    assert_raises_value_error(lambda: validate_upload_suffix("frame"), "missing suffix must be rejected")
    print("[OK] upload suffix model")


def test_frame_index_and_filename() -> None:
    assert_equal(sanitize_frame_index("frame-00123"), "00123", "frame index should keep digits")
    assert_equal(sanitize_frame_index("1234567890"), "12345678", "frame index should be capped")
    assert_equal(sanitize_frame_index("abc"), "", "frame index without digits should be empty")

    filename = build_upload_filename(
        "wx/session 01",
        "frame-00123",
        ".jpg",
        timestamp=datetime(2026, 6, 14, 12, 34, 56, 789),
        nonce="abcdef1234567890",
    )
    assert_equal(
        filename,
        "20260614123456_000789_wx_session_01_00123_abcdef1234567890.jpg",
        "upload filename should be stable and sanitized",
    )
    assert_true(
        re.match(r"^\d{14}_\d{6}_wx_[0-9a-f]{8}\.png$", build_upload_filename("wx", "", ".png")),
        "runtime filename should include timestamp and random suffix",
    )
    print("[OK] upload filename model")


def test_upload_destination() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        queue_root = root / "queue"
        watch_dir = root / "watch"

        job_id, save_dir = resolve_upload_destination(True, queue_root, watch_dir, "wx/session 01")
        assert_equal(job_id, "wx_session_01", "queue session id should be sanitized")
        assert_equal(save_dir, job_images_dir(queue_root, "wx_session_01"), "queue destination changed")

        job_id, save_dir = resolve_upload_destination(False, queue_root, watch_dir, "wx/session 01")
        assert_equal(job_id, "wx_session_01", "legacy session id should still be sanitized")
        assert_equal(save_dir, watch_dir, "legacy destination should use watch dir")
    print("[OK] upload destination model")


def test_upload_manifest_and_response() -> None:
    created_at = datetime(2026, 6, 14, 12, 34, 56)
    manifest = build_upload_manifest_row(
        filename="frame.jpg",
        size_bytes=123,
        phase="input",
        job_id="wx_01",
        frame_index="7",
        session_id="wx/session 01",
        created_at=created_at,
    )
    assert_equal(
        manifest,
        {
            "filename": "frame.jpg",
            "bytes": 123,
            "phase": "input",
            "job_id": "wx_01",
            "frame_index": "7",
            "session_id": "wx/session 01",
            "created_at": "2026-06-14T12:34:56Z",
        },
        "upload manifest row changed",
    )

    response = build_upload_response(
        filename="frame.jpg",
        size_bytes=123,
        phase="input",
        job_id="wx_01",
        queue_enabled=True,
        job={"id": "wx_01", "status": "queued"},
    )
    assert_equal(response["code"], 200, "upload response code changed")
    assert_true(response["ok"], "upload response ok flag changed")
    assert_equal(response["msg"], "上传成功", "upload response message changed")
    assert_equal(response["job_id"], "wx_01", "upload response job id changed")
    assert_true(response["queue_enabled"], "upload response queue flag changed")
    assert_equal(response["job"], {"id": "wx_01", "status": "queued"}, "upload response job changed")
    print("[OK] upload manifest and response model")


def main() -> None:
    test_upload_suffix()
    test_frame_index_and_filename()
    test_upload_destination()
    test_upload_manifest_and_response()
    print("[OK] upload model checks passed")


if __name__ == "__main__":
    main()
