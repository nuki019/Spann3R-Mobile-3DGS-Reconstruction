"""Static API contract checks that do not require backend dependencies."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DASHBOARD = ROOT / "backend" / "services" / "backend_dashboard.py"
UPLOAD_UTILS = ROOT / "frontend" / "utils" / "oss_upload_utils.js"
PREVIEW_JS = ROOT / "frontend" / "pages" / "preview" / "preview.js"
PREVIEW_WXML = ROOT / "frontend" / "pages" / "preview" / "preview.wxml"

REQUIRED_ROUTES = {
    ("GET", "/healthz"),
    ("GET", "/upload-proxy/healthz"),
    ("GET", "/upload-proxy/stats"),
    ("POST", "/upload-proxy/upload"),
    ("GET", "/api/status"),
    ("GET", "/api/progress"),
    ("GET", "/api/jobs"),
    ("POST", "/api/jobs/{job_id}/cancel"),
    ("GET", "/api/pointclouds/summary"),
    ("GET", "/download/latest"),
    ("GET", "/download/processed/latest"),
}

REQUIRED_FRONTEND_TERMS = {
    UPLOAD_UTILS: [
        "jobsApiUrl",
        "uploadProxyHealthUrl",
        "pointcloudsSummaryApiUrl",
        "optimizedLatestPointCloudUrl",
    ],
    PREVIEW_JS: [
        "buildJobsData",
        "cancelJob",
        "jobsApiUrl",
        "/cancel",
    ],
    PREVIEW_WXML: [
        "任务队列",
        "bindtap=\"cancelJob\"",
        "点云下载",
    ],
}

REQUIRED_DASHBOARD_HTML_TERMS = [
    "任务队列",
    "function renderJobs",
    'apiGet("/api/jobs")',
    "function cancelJob",
    "/api/jobs/${encodeURIComponent(jobId)}/cancel",
]


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def extract_routes(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    routes: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not isinstance(func, ast.Attribute):
                continue
            if not isinstance(func.value, ast.Name) or func.value.id != "app":
                continue
            method = func.attr.upper()
            if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                continue
            if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                continue
            route = decorator.args[0].value
            if isinstance(route, str):
                routes.add((method, route))
    return routes


def check_backend_routes() -> None:
    routes = extract_routes(BACKEND_DASHBOARD)
    missing = sorted(REQUIRED_ROUTES - routes)
    if missing:
        fail("missing backend routes: " + ", ".join(f"{method} {path}" for method, path in missing))
    print("[OK] API route contract")


def check_terms(path: Path, terms: list[str], label: str) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    for term in terms:
        if term not in text:
            fail(f"{label} missing term: {term}")


def check_frontend_contract() -> None:
    for path, terms in REQUIRED_FRONTEND_TERMS.items():
        check_terms(path, terms, str(path.relative_to(ROOT)))
    print("[OK] frontend contract")


def check_dashboard_contract() -> None:
    check_terms(BACKEND_DASHBOARD, REQUIRED_DASHBOARD_HTML_TERMS, "backend dashboard HTML")
    print("[OK] dashboard UI contract")


def main() -> None:
    check_backend_routes()
    check_frontend_contract()
    check_dashboard_contract()
    print("[OK] API contract checks passed")


if __name__ == "__main__":
    main()
