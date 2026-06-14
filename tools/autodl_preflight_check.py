"""AutoDL demo preflight checks for the Spann3R + 3DGS backend."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "README.md",
    "backend/.env.pipeline.4090.example",
    "backend/restart_backend_stack.sh",
    "backend/start_backend_ui.sh",
    "backend/start_backend_4090.sh",
    "backend/services/backend_dashboard.py",
    "backend/pipeline/backend_4090.py",
    "backend/pipeline/job_queue.py",
    "frontend/utils/oss_upload_utils.js",
]

REQUIRED_ENV_KEYS = [
    "PIPELINE_QUEUE_ENABLED",
    "PIPELINE_JOB_ROOT",
    "PIPELINE_JOB_ARCHIVE_ROOT",
    "PIPELINE_STATE_FILE",
    "NS_MAX_NUM_ITERATIONS",
    "NS_STEPS_PER_SAVE",
    "RESTART_UPLOAD_CLEANUP",
    "RESTART_QUEUE_CLEANUP",
]

HTTP_ENDPOINTS = [
    ("/healthz", "status"),
    ("/upload-proxy/healthz", "status"),
    ("/api/status", "running"),
    ("/api/progress", "phase"),
    ("/api/jobs", "items"),
    ("/api/pointclouds/summary", "summary"),
]


class CheckReport:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def ok(self, message: str) -> None:
        print(f"[OK] {message}")

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        print(f"[WARN] {message}")

    def error(self, message: str) -> None:
        self.errors.append(message)
        print(f"[FAIL] {message}")

    def finish(self) -> None:
        if self.errors:
            print(f"[FAIL] preflight failed: {len(self.errors)} error(s), {len(self.warnings)} warning(s)")
            raise SystemExit(1)
        print(f"[OK] preflight passed: {len(self.warnings)} warning(s)")


def read_env_example() -> dict[str, str]:
    env_path = ROOT / "backend" / ".env.pipeline.4090.example"
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def check_files(report: CheckReport) -> None:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    if missing:
        report.error("missing required files: " + ", ".join(missing))
        return
    report.ok("required repository files exist")


def check_env_example(report: CheckReport) -> None:
    values = read_env_example()
    missing = [key for key in REQUIRED_ENV_KEYS if key not in values]
    if missing:
        report.error("env example missing keys: " + ", ".join(missing))
        return

    if values.get("PIPELINE_QUEUE_ENABLED", "").lower() not in {"true", "1", "yes", "on"}:
        report.warn("PIPELINE_QUEUE_ENABLED is not enabled in the example config")
    if values.get("NS_MAX_NUM_ITERATIONS") != "1000":
        report.warn("NS_MAX_NUM_ITERATIONS is not 1000 in the example config")
    report.ok("example env contains required delivery keys")


def request_json(base_url: str, endpoint: str, timeout: float) -> dict[str, Any]:
    url = base_url.rstrip("/") + endpoint
    with urllib.request.urlopen(url, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
    payload = json.loads(body)
    return payload if isinstance(payload, dict) else {"value": payload}


def check_http(report: CheckReport, base_url: str, timeout: float) -> None:
    for endpoint, required_key in HTTP_ENDPOINTS:
        try:
            payload = request_json(base_url, endpoint, timeout)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
            report.error(f"{endpoint} unavailable: {error}")
            continue
        if required_key not in payload:
            report.error(f"{endpoint} response missing key: {required_key}")
            continue
        if endpoint.endswith("healthz") and payload.get("status") != "ok":
            report.error(f"{endpoint} returned status={payload.get('status')!r}")
            continue
        report.ok(f"{endpoint} reachable")

    try:
        upload_health = request_json(base_url, "/upload-proxy/healthz", timeout)
        if upload_health.get("allow_upload") is not True:
            report.warn("/upload-proxy/healthz does not currently allow upload")
        if upload_health.get("queue_enabled") is not True:
            report.warn("upload proxy queue mode is not enabled")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        pass


def check_disk(report: CheckReport, min_free_gb: float) -> None:
    candidates = [Path("/root/autodl-tmp"), ROOT]
    seen: set[Path] = set()
    for path in candidates:
        probe = path if path.exists() else path.parent
        if not probe.exists() or probe in seen:
            continue
        seen.add(probe)
        usage = shutil.disk_usage(probe)
        free_gb = usage.free / 1024 / 1024 / 1024
        if free_gb < min_free_gb:
            report.warn(f"low disk space at {probe}: {free_gb:.2f} GB free")
        else:
            report.ok(f"disk space at {probe}: {free_gb:.2f} GB free")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AutoDL demo preflight checks.")
    parser.add_argument("--base-url", default="http://127.0.0.1:6008", help="Dashboard base URL.")
    parser.add_argument("--timeout", type=float, default=3.0, help="HTTP timeout in seconds.")
    parser.add_argument("--offline", action="store_true", help="Skip live HTTP checks.")
    parser.add_argument("--min-free-gb", type=float, default=5.0, help="Warn below this free disk space.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = CheckReport()
    check_files(report)
    check_env_example(report)
    check_disk(report, min_free_gb=args.min_free_gb)
    if args.offline:
        report.ok("offline mode: skipped live 6008 HTTP checks")
    else:
        check_http(report, args.base_url, timeout=args.timeout)
    report.finish()


if __name__ == "__main__":
    main()
