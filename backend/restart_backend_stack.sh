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

UPLOAD_CLEANUP_MODE="${RESTART_UPLOAD_CLEANUP:-archive}"
UPLOAD_ARCHIVE_KEEP="${RESTART_UPLOAD_ARCHIVE_KEEP:-5}"
QUEUE_CLEANUP_MODE="${RESTART_QUEUE_CLEANUP:-${UPLOAD_CLEANUP_MODE}}"
QUEUE_ARCHIVE_KEEP="${RESTART_QUEUE_ARCHIVE_KEEP:-${UPLOAD_ARCHIVE_KEEP}}"
UPLOAD_DIRS=("${WATCH_DIR:-/root/autodl-tmp/input_images}")
if [[ -n "${UPLOAD_SAVE_DIR:-}" && "${UPLOAD_SAVE_DIR}" != "${WATCH_DIR:-/root/autodl-tmp/input_images}" ]]; then
  UPLOAD_DIRS+=("${UPLOAD_SAVE_DIR}")
fi
ARCHIVE_ROOT="${ARCHIVE_DIR:-/root/autodl-tmp/input_images_archive}"
QUEUE_ROOT="${PIPELINE_JOB_ROOT:-/root/autodl-tmp/pipeline_jobs}"
QUEUE_ARCHIVE_ROOT="${PIPELINE_JOB_ARCHIVE_ROOT:-/root/autodl-tmp/pipeline_jobs_archive}"

is_safe_cleanup_root() {
  local target="$1"
  [[ -n "${target}" && "${target}" != "/" && "${target}" != "." ]]
}

cleanup_upload_dir() {
  local upload_dir="$1"
  if ! is_safe_cleanup_root "${upload_dir}"; then
    echo "跳过危险上传目录: ${upload_dir}"
    return 0
  fi
  [[ -d "${upload_dir}" ]] || return 0

  shopt -s nullglob
  local files=("${upload_dir}"/*)
  shopt -u nullglob
  if [[ ${#files[@]} -eq 0 ]]; then
    echo "上传目录为空: ${upload_dir}"
    return 0
  fi

  case "${UPLOAD_CLEANUP_MODE}" in
    keep)
      echo "保留旧上传文件: ${upload_dir} (${#files[@]} 项)"
      ;;
    delete|clear)
      echo "清空旧上传文件: ${upload_dir} (${#files[@]} 项)"
      rm -rf -- "${files[@]}"
      ;;
    archive|"")
      local archive_dir="${ARCHIVE_ROOT}/restart_$(date +%Y%m%d_%H%M%S)"
      mkdir -p "${archive_dir}"
      echo "归档旧上传文件: ${upload_dir} -> ${archive_dir} (${#files[@]} 项)"
      mv -- "${files[@]}" "${archive_dir}/"
      ;;
    *)
      echo "未知 RESTART_UPLOAD_CLEANUP=${UPLOAD_CLEANUP_MODE}，为避免误删，保留旧上传文件。"
      ;;
  esac
}

prune_upload_archives() {
  [[ "${UPLOAD_CLEANUP_MODE}" == "archive" || "${UPLOAD_CLEANUP_MODE}" == "" ]] || return 0
  is_safe_cleanup_root "${ARCHIVE_ROOT}" || return 0
  [[ -d "${ARCHIVE_ROOT}" ]] || return 0
  [[ "${UPLOAD_ARCHIVE_KEEP}" =~ ^[0-9]+$ ]] || return 0

  mapfile -t old_archives < <(
    find "${ARCHIVE_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'restart_*' -printf '%T@ %p\n' \
      | sort -rn \
      | awk -v keep="${UPLOAD_ARCHIVE_KEEP}" 'NR > keep {sub(/^[^ ]+ /, ""); print}'
  )
  if [[ ${#old_archives[@]} -gt 0 ]]; then
    echo "清理旧上传归档，仅保留最近 ${UPLOAD_ARCHIVE_KEEP} 次。"
    rm -rf -- "${old_archives[@]}"
  fi
}

cleanup_queue_jobs() {
  if ! is_safe_cleanup_root "${QUEUE_ROOT}"; then
    echo "跳过危险队列目录: ${QUEUE_ROOT}"
    return 0
  fi
  [[ -d "${QUEUE_ROOT}" ]] || return 0

  shopt -s nullglob
  local jobs=("${QUEUE_ROOT}"/*)
  shopt -u nullglob
  local filtered_jobs=()
  local queue_archive_abs
  queue_archive_abs="$(readlink -f "${QUEUE_ARCHIVE_ROOT}" 2>/dev/null || true)"
  for job_path in "${jobs[@]}"; do
    local job_abs
    job_abs="$(readlink -f "${job_path}" 2>/dev/null || true)"
    if [[ -n "${queue_archive_abs}" && "${job_abs}" == "${queue_archive_abs}" ]]; then
      continue
    fi
    filtered_jobs+=("${job_path}")
  done
  jobs=("${filtered_jobs[@]}")
  if [[ ${#jobs[@]} -eq 0 ]]; then
    echo "队列任务目录为空: ${QUEUE_ROOT}"
    return 0
  fi

  case "${QUEUE_CLEANUP_MODE}" in
    keep)
      echo "保留旧队列任务: ${QUEUE_ROOT} (${#jobs[@]} 项)"
      ;;
    delete|clear)
      echo "清空旧队列任务: ${QUEUE_ROOT} (${#jobs[@]} 项)"
      rm -rf -- "${jobs[@]}"
      ;;
    archive|"")
      local archive_dir="${QUEUE_ARCHIVE_ROOT}/restart_$(date +%Y%m%d_%H%M%S)"
      mkdir -p "${archive_dir}"
      echo "归档旧队列任务: ${QUEUE_ROOT} -> ${archive_dir} (${#jobs[@]} 项)"
      mv -- "${jobs[@]}" "${archive_dir}/"
      ;;
    *)
      echo "未知 RESTART_QUEUE_CLEANUP=${QUEUE_CLEANUP_MODE}，为避免误删，保留旧队列任务。"
      ;;
  esac
}

prune_queue_archives() {
  [[ "${QUEUE_CLEANUP_MODE}" == "archive" || "${QUEUE_CLEANUP_MODE}" == "" ]] || return 0
  is_safe_cleanup_root "${QUEUE_ARCHIVE_ROOT}" || return 0
  [[ -d "${QUEUE_ARCHIVE_ROOT}" ]] || return 0
  [[ "${QUEUE_ARCHIVE_KEEP}" =~ ^[0-9]+$ ]] || return 0

  mapfile -t old_archives < <(
    find "${QUEUE_ARCHIVE_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'restart_*' -printf '%T@ %p\n' \
      | sort -rn \
      | awk -v keep="${QUEUE_ARCHIVE_KEEP}" 'NR > keep {sub(/^[^ ]+ /, ""); print}'
  )
  if [[ ${#old_archives[@]} -gt 0 ]]; then
    echo "清理旧队列归档，仅保留最近 ${QUEUE_ARCHIVE_KEEP} 次。"
    rm -rf -- "${old_archives[@]}"
  fi
}

echo "停止旧进程（backend/ui/upload/ns-train:6006）..."
PIDS="$(ps -ef | grep -E 'python(3)? .*(-m pipeline\.backend_4090|backend_4090\.py)|uvicorn (backend_dashboard:app|services\.backend_dashboard:app)|uvicorn (upload_server:app|services\.upload_server:app)|ns-train .*--viewer.websocket-port 6006' | grep -v grep | awk '{print $2}' | sort -u | tr '\n' ' ' || true)"
if [[ -n "${PIDS// }" ]]; then
  kill ${PIDS} || true
  sleep 2
fi

echo "处理旧上传文件（模式: ${UPLOAD_CLEANUP_MODE}）..."
for upload_dir in "${UPLOAD_DIRS[@]}"; do
  cleanup_upload_dir "${upload_dir}"
done
prune_upload_archives

echo "处理旧队列任务（模式: ${QUEUE_CLEANUP_MODE}）..."
cleanup_queue_jobs
prune_queue_archives

echo "启动 UI (6008)..."
bash "${SCRIPT_DIR}/start_backend_ui.sh"
sleep 1

echo "启动后端流水线 (6006 上传/Viewer)..."
bash "${SCRIPT_DIR}/start_backend_4090.sh"
sleep 1

echo
echo "当前关键进程："
ps -ef | grep -E 'backend_4090|backend_dashboard|ns-train|upload_server' | grep -v grep || true
echo
echo "健康检查："
curl -s http://127.0.0.1:6008/healthz || true
echo
echo "完成。日志目录: ${SCRIPT_DIR}/logs"
