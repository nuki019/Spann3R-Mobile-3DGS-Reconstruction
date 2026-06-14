const { canUploadByPhase } = require("./phase_policy");

function isUploadAllowed(phase, uploadHealthy, dashboardHealthy, uploadAllow) {
  if (!uploadHealthy) {
    return false;
  }
  if (typeof uploadAllow === "boolean") {
    return uploadAllow;
  }
  return canUploadByPhase(phase);
}

function getPhaseFromProgress(progressData) {
  const data = progressData || {};
  let phase = "";
  if (typeof data.phase === "string" && data.phase) {
    phase = data.phase;
  } else if (typeof data.stage === "string" && data.stage) {
    phase = data.stage;
  }
  return phase || "unknown";
}

function isHttpOkResponse(res) {
  const statusCode = res && res.statusCode ? res.statusCode : 0;
  return statusCode >= 200 && statusCode < 300;
}

function parseDashboardHealthResponse(res) {
  if (!isHttpOkResponse(res)) {
    return false;
  }
  const payload = res && res.data ? res.data : null;
  return Boolean(payload && typeof payload === "object" && payload.status === "ok");
}

function parseUploadProxyHealthResponse(res) {
  if (!isHttpOkResponse(res)) {
    return { ok: false };
  }
  const payload = res && res.data ? res.data : null;
  return {
    ok: Boolean(payload && typeof payload === "object" && payload.status === "ok"),
    allowUpload: payload && typeof payload.allow_upload === "boolean" ? payload.allow_upload : undefined,
    queueEnabled: Boolean(payload && payload.queue_enabled),
    phase: payload && typeof payload.phase === "string" ? payload.phase : ""
  };
}

function buildRefreshPhaseResult(phase, dashboardHealthy, uploadState) {
  const normalizedPhase = phase || "unknown";
  const uploadInfo = uploadState || { ok: false };
  const uploadHealthy = Boolean(uploadInfo && uploadInfo.ok);
  const uploadAllow = uploadInfo && typeof uploadInfo.allowUpload === "boolean" ? uploadInfo.allowUpload : undefined;
  const queueEnabled = Boolean(uploadInfo && uploadInfo.queueEnabled);
  const dashboardOk = Boolean(dashboardHealthy);
  return {
    phase: normalizedPhase,
    uploadHealthy: uploadHealthy,
    dashboardHealthy: dashboardOk,
    uploadAllow: uploadAllow,
    queueEnabled: queueEnabled,
    phaseAllowUpload: isUploadAllowed(normalizedPhase, uploadHealthy, dashboardOk, uploadAllow)
  };
}

function getPhaseText(phase) {
  const phaseMap = {
    input: "input（可上传）",
    spann3r: "spann3r（重建中）",
    gaussian: "gaussian（训练/导出中）",
    export: "export（点云导出中）",
    completed: "completed（可查看/下载）",
    stopped: "stopped（已停止）",
    failed: "failed（失败）",
    idle: "idle（空闲）",
    unknown: "unknown（未知）"
  };
  return phaseMap[phase] || (phase + "（未知映射）");
}

function getPhaseHint(phase, uploadHealthy, dashboardHealthy, uploadAllow, queueEnabled) {
  if (isUploadAllowed(phase, uploadHealthy, dashboardHealthy, uploadAllow)) {
    return queueEnabled ? "队列上传就绪，可继续提交新任务" : "上传服务就绪，可提交本批照片";
  }
  if (phase === "spann3r") {
    return "Spann3R 重建处理中，上传已禁用";
  }
  if (phase === "gaussian" || phase === "export" || phase === "completed") {
    return "当前为查看或导出阶段，上传暂不可用";
  }
  if (canUploadByPhase(phase) && dashboardHealthy && !uploadHealthy) {
    return "状态服务已连通，但上传代理未就绪（检查 /upload-proxy/healthz）";
  }
  if (canUploadByPhase(phase) && !dashboardHealthy) {
    return "健康检查未通过（请检查 uu 域名 /healthz）";
  }
  if (phase === "idle" || phase === "stopped") {
    return "可在后端管理台启动流程；健康检查通过后可直接上传";
  }
  return "后端阶段未知，请检查 /api/progress 与 /healthz";
}

function getBackendStatusLabel(phase, uploadHealthy, dashboardHealthy, uploadAllow) {
  if (isUploadAllowed(phase, uploadHealthy, dashboardHealthy, uploadAllow)) {
    return "后端就绪";
  }
  if (!uploadHealthy && !dashboardHealthy) {
    return "等待服务";
  }
  if (canUploadByPhase(phase) && !uploadHealthy) {
    return "等待上传服务";
  }
  if (phase === "spann3r") {
    return "重建中";
  }
  if (phase === "gaussian") {
    return "训练中";
  }
  if (phase === "export") {
    return "导出中";
  }
  if (phase === "completed") {
    return "已完成";
  }
  if (phase === "failed") {
    return "失败";
  }
  return "暂不可传";
}

function getBackendStatusClass(phase, uploadHealthy, dashboardHealthy, uploadAllow) {
  if (isUploadAllowed(phase, uploadHealthy, dashboardHealthy, uploadAllow)) {
    return "ok";
  }
  if (!uploadHealthy && !dashboardHealthy) {
    return "idle";
  }
  if (canUploadByPhase(phase) && !uploadHealthy) {
    return "warn";
  }
  if (phase === "spann3r" || phase === "gaussian" || phase === "export" || phase === "failed") {
    return "warn";
  }
  return "idle";
}

function getUploadBlockLabel(phase, uploadHealthy, dashboardHealthy) {
  if (!uploadHealthy && !dashboardHealthy) {
    return "等待服务";
  }
  if (canUploadByPhase(phase) && !uploadHealthy) {
    return "等待上传服务";
  }
  if (phase === "spann3r") {
    return "重建中";
  }
  if (phase === "gaussian") {
    return "训练中";
  }
  if (phase === "export") {
    return "导出中";
  }
  if (phase === "completed") {
    return "已完成";
  }
  if (phase === "failed") {
    return "失败";
  }
  return "暂不可传";
}

function buildPhaseState(phase, uploadHealthy, dashboardHealthy, uploadAllow, queueEnabled) {
  const normalizedPhase = phase || "unknown";
  const healthOk = Boolean(uploadHealthy);
  const dashboardOk = Boolean(dashboardHealthy);
  const allowUpload = isUploadAllowed(normalizedPhase, healthOk, dashboardOk, uploadAllow);
  return {
    currentPhase: normalizedPhase,
    phaseText: getPhaseText(normalizedPhase),
    phaseAllowUpload: allowUpload,
    backendStatusLabel: getBackendStatusLabel(normalizedPhase, healthOk, dashboardOk, uploadAllow),
    backendStatusClass: getBackendStatusClass(normalizedPhase, healthOk, dashboardOk, uploadAllow),
    uploadBlockLabel: getUploadBlockLabel(normalizedPhase, healthOk, dashboardOk),
    uploadHealthOk: healthOk,
    dashboardHealthOk: dashboardOk,
    queueUploadEnabled: Boolean(queueEnabled),
    phaseHint: getPhaseHint(normalizedPhase, healthOk, dashboardOk, uploadAllow, queueEnabled)
  };
}

module.exports = {
  buildRefreshPhaseResult,
  buildPhaseState,
  canUploadByPhase,
  getBackendStatusClass,
  getBackendStatusLabel,
  getPhaseFromProgress,
  getPhaseHint,
  getPhaseText,
  getUploadBlockLabel,
  isHttpOkResponse,
  isUploadAllowed,
  parseDashboardHealthResponse,
  parseUploadProxyHealthResponse
};
