#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

export PATH="/root/miniconda3/bin:/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

if [[ -f "${SCRIPT_DIR}/.env.pipeline.4090" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/.env.pipeline.4090"
  set +a
fi

LOG_DIR="${LOG_DIR:-${SCRIPT_DIR}/logs}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python || echo /root/miniconda3/bin/python)}"
mkdir -p "${LOG_DIR}"

OLD_PIDS="$(ps -ef | grep -E 'python(3)? .*(backend_4090\.py|-m pipeline\.backend_4090)' | grep -v grep | awk '{print $2}' || true)"
if [[ -n "${OLD_PIDS}" ]]; then
  echo "检测到旧 backend_4090 进程，先停止: ${OLD_PIDS}"
  kill ${OLD_PIDS} || true
  sleep 1
fi

nohup "${PYTHON_BIN}" -u -m pipeline.backend_4090 > "${LOG_DIR}/backend_4090.log" 2>&1 &
PID=$!
echo "${PID}" > "${LOG_DIR}/backend_4090.pid"

echo "4090 后端已启动，PID: ${PID}"
echo "日志: ${LOG_DIR}/backend_4090.log"
if [[ "${PIPELINE_QUEUE_ENABLED:-true}" =~ ^(1|true|TRUE|yes|YES|y|Y|on|ON)$ ]]; then
  echo "队列模式: 6008 /upload-proxy 写入 ${PIPELINE_JOB_ROOT:-/root/autodl-tmp/pipeline_jobs}，6006 固定留给 Viewer"
else
  echo "单端口模式: ${UPLOAD_PORT:-6006} 上传完成后释放端口，6006 切换为 Viewer"
fi
