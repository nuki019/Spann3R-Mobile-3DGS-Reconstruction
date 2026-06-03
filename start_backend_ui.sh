#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if [[ -f "${SCRIPT_DIR}/.env.pipeline.4090" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/.env.pipeline.4090"
  set +a
fi

LOG_DIR="${LOG_DIR:-${SCRIPT_DIR}/logs}"
DASHBOARD_PORT="${DASHBOARD_PORT:-6008}"
mkdir -p "${LOG_DIR}"

OLD_PIDS="$(ps -ef | grep -E 'uvicorn (backend_dashboard:app|services\\.backend_dashboard:app)' | grep -v grep | awk '{print $2}' || true)"
if [[ -n "${OLD_PIDS}" ]]; then
  echo "检测到旧 backend_dashboard 进程，先停止: ${OLD_PIDS}"
  kill ${OLD_PIDS} || true
  sleep 1
fi

nohup python -m uvicorn services.backend_dashboard:app \
  --host 0.0.0.0 \
  --port "${DASHBOARD_PORT}" \
  > "${LOG_DIR}/backend_dashboard.log" 2>&1 &
DASHBOARD_PID=$!

echo "后端可视化 UI 已启动，PID: ${DASHBOARD_PID}，端口: ${DASHBOARD_PORT}"
echo "UI 地址: http://0.0.0.0:${DASHBOARD_PORT}"
echo "点云下载页: http://0.0.0.0:${DASHBOARD_PORT}/downloads"
echo "上传代理: http://0.0.0.0:${DASHBOARD_PORT}/upload-proxy/upload -> ${UPLOAD_PROXY_TARGET:-http://127.0.0.1:${UPLOAD_INTERNAL_PORT:-7006}}/upload"
echo "日志: ${LOG_DIR}/backend_dashboard.log"
echo "端口规划: 6006(Viewer) + ${DASHBOARD_PORT}(UI/下载/上传代理)"
