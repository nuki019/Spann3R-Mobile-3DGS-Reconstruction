function normalizeKey(value) {
  return String(value || "").trim().toLowerCase();
}

function canUploadByPhase(phase) {
  const normalized = normalizeKey(phase);
  return normalized === "idle" ||
    normalized === "input" ||
    normalized === "upload" ||
    normalized === "stopped" ||
    normalized === "unknown";
}

function canCancelJobStatus(status) {
  const normalized = normalizeKey(status);
  return normalized === "queued" ||
    normalized === "uploading" ||
    normalized === "ready";
}

module.exports = {
  canCancelJobStatus,
  canUploadByPhase,
  normalizeKey
};
