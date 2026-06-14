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
    ROOT / "backend" / "services" / "pointcloud_download_server.py",
    ROOT / "backend" / "services" / "pointcloud_index.py",
    ROOT / "backend" / "services" / "progress_model.py",
    ROOT / "backend" / "services" / "upload_model.py",
    ROOT / "backend" / "services" / "upload_server.py",
    ROOT / "backend" / "pipeline" / "command_model.py",
    ROOT / "backend" / "pipeline" / "job_policy.py",
    ROOT / "backend" / "pipeline" / "job_queue.py",
    ROOT / "backend" / "pipeline" / "storage_model.py",
    ROOT / "backend" / "pipeline" / "task_state.py",
    ROOT / "backend" / "pipeline" / "auto_gs.py",
    ROOT / "backend" / "pipeline" / "backend_4090.py",
    ROOT / "tools" / "smoke_check_delivery.py",
    ROOT / "tools" / "api_contract_check.py",
    ROOT / "tools" / "autodl_preflight_check.py",
    ROOT / "tools" / "test_frontend_config.py",
    ROOT / "tools" / "test_command_model.py",
    ROOT / "tools" / "test_pipeline_models.py",
    ROOT / "tools" / "test_pointcloud_downloads.py",
    ROOT / "tools" / "test_progress_model.py",
    ROOT / "tools" / "test_storage_model.py",
    ROOT / "tools" / "test_upload_model.py",
]

JS_FILES = [
    ROOT / "frontend" / "pages" / "capture" / "capture.js",
    ROOT / "frontend" / "pages" / "preview" / "preview.js",
    ROOT / "frontend" / "utils" / "oss_upload_utils.js",
    ROOT / "frontend" / "utils" / "preview_state_model.js",
    ROOT / "tools" / "test_preview_state_model.js",
]

TEXT_FILES_TO_SCAN = [
    ROOT / "README.md",
    ROOT / "backend" / "docs" / "user_guide_cn.md",
    ROOT / "backend" / "docs" / "autodl_ops_commands_cn.md",
    ROOT / "backend" / ".env.pipeline.4090.example",
    ROOT / "backend" / "restart_backend_stack.sh",
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
        "api_contract_check.py",
        "autodl_preflight_check.py",
        "test_frontend_config.py",
        "test_preview_state_model.js",
        "test_command_model.py",
        "test_pipeline_models.py",
        "test_pointcloud_downloads.py",
        "test_progress_model.py",
        "test_storage_model.py",
        "test_upload_model.py",
        "6008",
        "点云下载",
        "RESTART_QUEUE_CLEANUP",
    ]
    for item in required:
        if item not in readme:
            fail(f"README missing required delivery term: {item}")

    gitattributes = (ROOT / ".gitattributes").read_text(encoding="utf-8", errors="ignore")
    if "*.sh text eol=lf" not in gitattributes:
        fail(".gitattributes must force LF for shell scripts")

    restart_script = (ROOT / "backend" / "restart_backend_stack.sh").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    for item in [
        "PIPELINE_JOB_ROOT",
        "PIPELINE_JOB_ARCHIVE_ROOT",
        "RESTART_QUEUE_CLEANUP",
        "RESTART_QUEUE_ARCHIVE_KEEP",
        "is_safe_cleanup_root",
        "cleanup_queue_jobs",
        "prune_queue_archives",
    ]:
        if item not in restart_script:
            fail(f"restart script missing queue cleanup term: {item}")
    print("[OK] required delivery text")


def check_backend_routes() -> None:
    dashboard = (ROOT / "backend" / "services" / "backend_dashboard.py").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    required_routes = [
        '@app.get("/healthz")',
        '@app.get("/upload-proxy/healthz")',
        '@app.post("/upload-proxy/upload")',
        '@app.get("/api/status")',
        '@app.get("/api/progress")',
        '@app.get("/api/jobs")',
        '@app.post("/api/jobs/{job_id}/cancel")',
        '@app.get("/api/pointclouds/summary")',
        '@app.get("/download/processed/latest")',
    ]
    for route in required_routes:
        if route not in dashboard:
            fail(f"backend dashboard missing route: {route}")
    print("[OK] backend route presence")


def check_frontend_queue_entrypoints() -> None:
    preview_js = (ROOT / "frontend" / "pages" / "preview" / "preview.js").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    preview_wxml = (ROOT / "frontend" / "pages" / "preview" / "preview.wxml").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    upload_utils = (ROOT / "frontend" / "utils" / "oss_upload_utils.js").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    required_terms = [
        (upload_utils, "jobsApiUrl"),
        (preview_js, "buildJobsData"),
        (preview_js, "cancelJob"),
        (preview_js, "/cancel"),
        (preview_wxml, "任务队列"),
        (preview_wxml, "bindtap=\"cancelJob\""),
    ]
    for text, term in required_terms:
        if term not in text:
            fail(f"frontend queue entrypoint missing: {term}")
    print("[OK] frontend queue entrypoints")


def check_frontend_capture_copy() -> None:
    capture_js = (ROOT / "frontend" / "pages" / "capture" / "capture.js").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    capture_json = (ROOT / "frontend" / "pages" / "capture" / "capture.json").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    forbidden_terms = [
        "上传到6006",
        "6006上传",
    ]
    for term in forbidden_terms:
        if term in capture_js or term in capture_json:
            fail(f"capture page still exposes outdated upload copy: {term}")
    if "上传中" not in capture_js:
        fail("capture page should use generic upload progress copy")
    print("[OK] frontend capture copy")


def check_api_contract_script() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "api_contract_check.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"api contract check failed\n{result.stdout}\n{result.stderr}")
    print(result.stdout.rstrip())


def check_pipeline_model_tests() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "test_pipeline_models.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"pipeline model tests failed\n{result.stdout}\n{result.stderr}")
    print(result.stdout.rstrip())


def check_frontend_config_tests() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "test_frontend_config.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"frontend config tests failed\n{result.stdout}\n{result.stderr}")
    print(result.stdout.rstrip())


def check_preview_state_model_tests() -> None:
    result = subprocess.run(
        ["node", str(ROOT / "tools" / "test_preview_state_model.js")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"preview state model tests failed\n{result.stdout}\n{result.stderr}")
    print(result.stdout.rstrip())


def check_command_model_tests() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "test_command_model.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"command model tests failed\n{result.stdout}\n{result.stderr}")
    print(result.stdout.rstrip())


def check_upload_model_tests() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "test_upload_model.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"upload model tests failed\n{result.stdout}\n{result.stderr}")
    print(result.stdout.rstrip())


def check_progress_model_tests() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "test_progress_model.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"progress model tests failed\n{result.stdout}\n{result.stderr}")
    print(result.stdout.rstrip())


def check_storage_model_tests() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "test_storage_model.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"storage model tests failed\n{result.stdout}\n{result.stderr}")
    print(result.stdout.rstrip())


def check_pointcloud_download_tests() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "test_pointcloud_downloads.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"pointcloud download tests failed\n{result.stdout}\n{result.stderr}")
    print(result.stdout.rstrip())


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
    check_backend_routes()
    check_frontend_queue_entrypoints()
    check_frontend_capture_copy()
    check_api_contract_script()
    check_frontend_config_tests()
    check_preview_state_model_tests()
    check_command_model_tests()
    check_upload_model_tests()
    check_progress_model_tests()
    check_storage_model_tests()
    check_pipeline_model_tests()
    check_pointcloud_download_tests()
    check_job_queue_smoke()
    print("[OK] delivery smoke checks passed")


if __name__ == "__main__":
    main()
