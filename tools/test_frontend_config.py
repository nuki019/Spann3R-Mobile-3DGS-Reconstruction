"""Offline checks for mini program routing and backend URL configuration."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
APP_JSON = FRONTEND / "app.json"
UPLOAD_UTILS = FRONTEND / "utils" / "oss_upload_utils.js"
CAPTURE_JSON = FRONTEND / "pages" / "capture" / "capture.json"
CAPTURE_JS = FRONTEND / "pages" / "capture" / "capture.js"
PREVIEW_JS = FRONTEND / "pages" / "preview" / "preview.js"
PREVIEW_WXML = FRONTEND / "pages" / "preview" / "preview.wxml"


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_const(text: str, name: str) -> str:
    match = re.search(rf'const\s+{re.escape(name)}\s*=\s*"([^"]+)"', text)
    if not match:
        fail(f"missing JS constant: {name}")
    return match.group(1)


def check_app_json() -> None:
    data = json.loads(read_text(APP_JSON))
    pages = data.get("pages")
    expect(isinstance(pages, list) and pages[0] == "pages/capture/capture", "capture must be first page")

    request_domains = data.get("serverDomain", {}).get("request", [])
    upload_domains = data.get("serverDomain", {}).get("uploadFile", [])
    expect(isinstance(request_domains, list) and request_domains, "request domain whitelist is empty")
    expect(isinstance(upload_domains, list) and upload_domains, "uploadFile domain whitelist is empty")

    upload_utils = read_text(UPLOAD_UTILS)
    dashboard_base = extract_const(upload_utils, "DASHBOARD_BASE_URL")
    viewer_base = extract_const(upload_utils, "VIEWER_BASE_URL")
    expect(dashboard_base in request_domains, "dashboard base URL must be in request whitelist")
    expect(dashboard_base in upload_domains, "dashboard base URL must be in uploadFile whitelist")
    expect(viewer_base in request_domains, "viewer base URL must be in request whitelist")
    print("[OK] app.json backend domains")


def check_upload_proxy_config() -> None:
    text = read_text(UPLOAD_UTILS)
    expect(
        "const UPLOAD_PROXY_BASE_URL = `${DASHBOARD_BASE_URL}/upload-proxy`;" in text,
        "upload proxy must be based on dashboard 6008 URL",
    )
    expect("const UPLOAD_API = `${UPLOAD_PROXY_BASE_URL}/upload`;" in text, "upload API path changed")
    expect("wx.uploadFile" in text, "upload utility must call wx.uploadFile")
    expect("session_id" in text and "frame_index" in text, "upload form data must include session/frame fields")
    expect("buildUploadSessionId" in text, "upload session id builder missing")
    print("[OK] upload proxy config")


def check_capture_page_copy() -> None:
    capture_json = read_text(CAPTURE_JSON)
    capture_js = read_text(CAPTURE_JS)
    forbidden = ["上传到6006", "6006上传"]
    for term in forbidden:
        expect(term not in capture_json and term not in capture_js, f"outdated capture copy: {term}")
    expect("双筛采集" in capture_json, "capture navigation title should stay concise")
    expect("上传中" in capture_js, "capture upload progress should use generic copy")
    print("[OK] capture page copy")


def check_preview_delivery_entries() -> None:
    preview_js = read_text(PREVIEW_JS)
    preview_wxml = read_text(PREVIEW_WXML)
    required_terms = [
        "copyViewerUrl",
        "copyDownloadsUrl",
        "copyOptimizedLatestPointCloudUrl",
        "copyGaussianZipUrl",
        "copyPointcloudDownloadUrl",
        "copyPointcloudRawUrl",
        "copyPointcloudZipUrl",
        "buildPointcloudSummary",
        "normalizePointcloudItem",
        "cancelJob",
    ]
    for term in required_terms:
        expect(term in preview_js or term in preview_wxml, f"preview delivery entry missing: {term}")
    expect("小程序不内嵌 WebView" in preview_wxml, "preview should explain external browser flow")
    print("[OK] preview delivery entries")


def check_no_webview() -> None:
    for path in FRONTEND.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".js", ".json", ".wxml", ".wxss"}:
            text = read_text(path).lower()
            expect("<web-view" not in text and "web-view" not in text, f"WebView is not allowed: {path}")
    print("[OK] no WebView usage")


def main() -> None:
    check_app_json()
    check_upload_proxy_config()
    check_capture_page_copy()
    check_preview_delivery_entries()
    check_no_webview()
    print("[OK] frontend config checks passed")


if __name__ == "__main__":
    main()
