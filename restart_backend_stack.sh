#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "停止旧进程（backend/ui/upload/ns-train）..."
PIDS="$(ps -ef | grep -E 'python(3)? .*(-m pipeline\.backend_4090|backend_4090\.py)|uvicorn (backend_dashboard:app|services\.backend_dashboard:app)|uvicorn (upload_server:app|services\.upload_server:app)|ns-train .*--viewer.websocket-port 6006' | grep -v grep | awk '{print $2}' | sort -u | tr '\n' ' ' || true)"
if [[ -n "${PIDS// }" ]]; then
  kill ${PIDS} || true
  sleep 2
fi

echo "启动 UI (6008)..."
bash "${SCRIPT_DIR}/start_backend_ui.sh"
sleep 1

echo "启动后端流水线 (内部上传 + 6006 Viewer)..."
bash "${SCRIPT_DIR}/start_backend_4090.sh"
for _ in {1..20}; do
  if curl -fsS http://127.0.0.1:6008/upload-proxy/healthz >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

echo
echo "当前关键进程："
ps -ef | grep -E 'backend_4090|backend_dashboard|ns-train|upload_server' | grep -v grep || true
echo
echo "健康检查："
curl -s http://127.0.0.1:6008/healthz || true
echo
curl -s http://127.0.0.1:6008/upload-proxy/healthz || true
echo
echo "完成。日志目录: ${SCRIPT_DIR}/logs"
