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
mkdir -p "${LOG_DIR}"

OLD_PIDS="$(ps -ef | grep -E 'python(3)? .*(backend_4090\.py|-m pipeline\.backend_4090)' | grep -v grep | awk '{print $2}' || true)"
if [[ -n "${OLD_PIDS}" ]]; then
  echo "检测到旧 backend_4090 进程，先停止: ${OLD_PIDS}"
  kill ${OLD_PIDS} || true
  sleep 1
fi

nohup python -u -m pipeline.backend_4090 > "${LOG_DIR}/backend_4090.log" 2>&1 &
PID=$!
echo "${PID}" > "${LOG_DIR}/backend_4090.pid"

echo "4090 后端已启动，PID: ${PID}"
echo "日志: ${LOG_DIR}/backend_4090.log"
echo "端口规划: 6008 /upload-proxy -> 内部上传端口 ${UPLOAD_INTERNAL_PORT:-${UPLOAD_PORT:-7006}}，6006 固定留给 Viewer"
