#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if [[ -f "${SCRIPT_DIR}/.env.pipeline" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/.env.pipeline"
  set +a
fi

LOG_DIR="${LOG_DIR:-${SCRIPT_DIR}/logs}"
UPLOAD_PORT="${UPLOAD_PORT:-6008}"
mkdir -p "${LOG_DIR}"

echo "启动上传服务与自动训练流水线..."

nohup python -m uvicorn services.upload_server:app \
  --host 0.0.0.0 \
  --port "${UPLOAD_PORT}" \
  > "${LOG_DIR}/upload_server.log" 2>&1 &
UPLOAD_PID=$!

nohup python -u -m pipeline.auto_gs \
  > "${LOG_DIR}/auto_gs.log" 2>&1 &
PIPELINE_PID=$!

echo "上传服务 PID: ${UPLOAD_PID}"
echo "流水线 PID: ${PIPELINE_PID}"
echo "日志目录: ${LOG_DIR}"
echo "上传接口: http://0.0.0.0:${UPLOAD_PORT}/upload"
echo "训练可视化端口: ${VIEWER_PORT:-6006}"
