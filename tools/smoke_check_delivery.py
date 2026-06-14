"""Delivery smoke checks for docs, configs and lightweight source validity."""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PYTHON_FILES = [
    ROOT / "backend" / "services" / "backend_dashboard.py",
    ROOT / "backend" / "services" / "upload_server.py",
    ROOT / "backend" / "pipeline" / "job_queue.py",
    ROOT / "backend" / "pipeline" / "task_state.py",
    ROOT / "backend" / "pipeline" / "auto_gs.py",
    ROOT / "backend" / "pipeline" / "backend_4090.py",
    ROOT / "tools" / "smoke_check_delivery.py",
]

JS_FILES = [
    ROOT / "frontend" / "pages" / "capture" / "capture.js",
    ROOT / "frontend" / "pages" / "preview" / "preview.js",
    ROOT / "frontend" / "utils" / "oss_upload_utils.js",
]

TEXT_FILES_TO_SCAN = [
    ROOT / "README.md",
    ROOT / "backend" / "docs" / "user_guide_cn.md",
    ROOT / "backend" / "docs" / "autodl_ops_commands_cn.md",
    ROOT / "backend" / ".env.pipeline.4090.example",
    ROOT / "frontend" / "utils" / "oss_upload_utils.js",
]

FORBIDDEN_PATTERNS = [
    re.compile(r"password\s*[:=]\s*[^\\s`]+", re.IGNORECASE),
    re.compile(r"passwd\s*[:=]\s*[^\\s`]+", re.IGNORECASE),
    re.compile(r"secret\s*[:=]\s*[^\\s`]+", re.IGNORECASE),
]

KNOWN_SECRET_SHA256 = {
    "9fab6e25036ae2fb60bd3624fb7ca024e3c33f5b4e8a7c42da8ac600fe11a3dc",
    "caeb1659542876903c476bc418d16749cbc41346bac2e93904fa7fddb883cf73",
}

SECRET_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+/_=.-]{8,}")


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def check_exists(paths: list[Path]) -> None:
    for path in paths:
        if not path.exists():
            fail(f"missing required file: {path.relative_to(ROOT)}")


def check_python_syntax(paths: list[Path]) -> None:
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        print(f"[OK] python syntax: {path.relative_to(ROOT)}")


def check_js_syntax(paths: list[Path]) -> None:
    for path in paths:
        result = subprocess.run(
            ["node", "-c", str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            fail(f"node syntax failed for {path.relative_to(ROOT)}\n{result.stderr}")
        print(f"[OK] js syntax: {path.relative_to(ROOT)}")


def check_no_secrets(paths: list[Path]) -> None:
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(text):
                fail(f"possible secret in {path.relative_to(ROOT)}: {pattern.pattern}")
        for match in SECRET_CANDIDATE_RE.finditer(text):
            digest = hashlib.sha256(match.group(0).encode("utf-8")).hexdigest()
            if digest in KNOWN_SECRET_SHA256:
                fail(f"known private credential in {path.relative_to(ROOT)}")
        print(f"[OK] secret scan: {path.relative_to(ROOT)}")


def check_required_text() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="ignore")
    required = [
        "upload-proxy",
        "NS_MAX_NUM_ITERATIONS",
        "smoke_check_delivery.py",
        "6008",
        "点云下载",
    ]
    for item in required:
        if item not in readme:
            fail(f"README missing required delivery term: {item}")

    gitattributes = (ROOT / ".gitattributes").read_text(encoding="utf-8", errors="ignore")
    if "*.sh text eol=lf" not in gitattributes:
        fail(".gitattributes must force LF for shell scripts")
    print("[OK] required delivery text")


def check_job_queue_smoke() -> None:
    sys.path.insert(0, str(ROOT / "backend"))
    from pipeline.job_queue import (  # pylint: disable=import-outside-toplevel
        job_images_dir,
        list_runnable_jobs,
        mark_job,
        record_uploaded_frame,
        sanitize_job_id,
        summarize_jobs,
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        queue_root = Path(tmp_dir)
        job_id = sanitize_job_id("wx/session 01")
        images_dir = job_images_dir(queue_root, job_id)
        images_dir.mkdir(parents=True, exist_ok=True)
        (images_dir / "frame_000.jpg").write_bytes(b"fake-jpeg")

        job = record_uploaded_frame(
            queue_root,
            job_id,
            filename="frame_000.jpg",
            size_bytes=9,
            frame_index="0",
            source_name="frame.jpg",
        )
        if job.get("status") != "queued":
            fail("job queue did not create a queued job")
        if len(list_runnable_jobs(queue_root)) != 1:
            fail("job queue did not expose the queued job as runnable")

        mark_job(queue_root, job_id, "running", "running in smoke test")
        record_uploaded_frame(
            queue_root,
            job_id,
            filename="frame_001.jpg",
            size_bytes=9,
            frame_index="1",
            source_name="frame.jpg",
        )
        if len(list_runnable_jobs(queue_root)) != 0:
            fail("late uploads must not reset running jobs to queued")

        mark_job(queue_root, job_id, "stopped", "cancelled in smoke test")
        if list_runnable_jobs(queue_root):
            fail("stopped jobs must not be runnable")
        summary = summarize_jobs(queue_root)
        if summary.get("count") != 1 or summary.get("queued") != 0:
            fail("job queue summary is inconsistent")
    print("[OK] job queue smoke")


def main() -> None:
    check_exists(PYTHON_FILES + JS_FILES + TEXT_FILES_TO_SCAN)
    check_python_syntax(PYTHON_FILES)
    check_js_syntax(JS_FILES)
    check_no_secrets(TEXT_FILES_TO_SCAN)
    check_required_text()
    check_job_queue_smoke()
    print("[OK] delivery smoke checks passed")


if __name__ == "__main__":
    main()
