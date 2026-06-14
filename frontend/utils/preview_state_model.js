const phasePolicy = require("./phase_policy");

function pickNumber(obj, keys) {
  if (!obj || typeof obj !== "object") {
    return null;
  }
  for (let i = 0; i < keys.length; i += 1) {
    const value = obj[keys[i]];
    if (typeof value === "number" && !Number.isNaN(value)) {
      return value;
    }
    if (typeof value === "string" && value.trim() !== "") {
      const parsed = Number(value);
      if (!Number.isNaN(parsed)) {
        return parsed;
      }
    }
  }
  return null;
}

function pickString(obj, keys) {
  if (!obj || typeof obj !== "object") {
    return "";
  }
  for (let i = 0; i < keys.length; i += 1) {
    const value = obj[keys[i]];
    if (typeof value === "string" && value) {
      return value;
    }
  }
  return "";
}

function toObject(data) {
  if (!data) {
    return {};
  }
  if (typeof data === "object") {
    return data;
  }
  if (typeof data === "string") {
    try {
      const parsed = JSON.parse(data);
      if (parsed && typeof parsed === "object") {
        return parsed;
      }
    } catch (e) {
      return {};
    }
  }
  return {};
}

function clipText(text, limit) {
  if (!text || text.length <= limit) {
    return text;
  }
  return text.slice(0, limit) + "...";
}

function asText(data, limit) {
  if (data === null || data === undefined) {
    return "-";
  }
  if (typeof data === "string") {
    return clipText(data, limit || 120);
  }
  try {
    return clipText(JSON.stringify(data), limit || 120);
  } catch (e) {
    return "-";
  }
}

function formatBytes(bytes) {
  if (typeof bytes !== "number" || Number.isNaN(bytes) || bytes < 0) {
    return "-";
  }
  if (bytes < 1024) {
    return bytes + " B";
  }
  const kb = bytes / 1024;
  if (kb < 1024) {
    return kb.toFixed(2) + " KB";
  }
  const mb = kb / 1024;
  if (mb < 1024) {
    return mb.toFixed(2) + " MB";
  }
  const gb = mb / 1024;
  return gb.toFixed(2) + " GB";
}

function toDashboardAbsoluteUrl(pathOrUrl, dashboardUrl) {
  if (!pathOrUrl) {
    return "";
  }
  if (/^https?:\/\//.test(pathOrUrl)) {
    return pathOrUrl;
  }
  const base = (dashboardUrl || "").replace(/\/$/, "");
  const path = pathOrUrl.charAt(0) === "/" ? pathOrUrl : "/" + pathOrUrl;
  return base + path;
}

function withQuery(url, query) {
  if (!url) {
    return "";
  }
  return url + (url.indexOf("?") >= 0 ? "&" : "?") + query;
}

function canUploadByPhase(phase) {
  return phasePolicy.canUploadByPhase(phase);
}

function canCancelJobStatus(status) {
  return phasePolicy.canCancelJobStatus(status);
}

function jobStatusClass(status) {
  if (status === "running") {
    return "running";
  }
  if (status === "completed") {
    return "done";
  }
  if (status === "failed" || status === "stopped") {
    return "warn";
  }
  return "pending";
}

function normalizeJobItem(item, index, statusTextFn) {
  const obj = toObject(item);
  const status = pickString(obj, ["status"]) || "unknown";
  const jobId = pickString(obj, ["id", "job_id"]) || ("job_" + index);
  const imageCount = pickNumber(obj, ["image_count", "uploaded_images"]);
  const sceneName = pickString(obj, ["scene_name"]) || "-";
  const updatedAt = pickString(obj, ["updated_at", "created_at", "completed_at"]) || "-";
  const labelFn = typeof statusTextFn === "function" ? statusTextFn : function(value) { return value || "-"; };
  return {
    id: jobId,
    status: status,
    statusText: labelFn(status),
    statusClass: jobStatusClass(status),
    sceneText: sceneName,
    imageText: imageCount === null ? "-" : String(imageCount),
    updatedAt: updatedAt,
    message: clipText(pickString(obj, ["message", "error"]) || "", 80),
    canCancel: canCancelJobStatus(status)
  };
}

function inferPointcloudType(obj) {
  const item = toObject(obj);
  const variant = (item.variant || "other").toLowerCase();
  const name = (item.name || "").toLowerCase();
  const path = (item.path || "").toLowerCase();
  const stepMatch = name.match(/(?:step|iter|iteration)[_-]?(\d+)/) || path.match(/(?:step|iter|iteration)[_-]?(\d+)/);
  const stepText = stepMatch ? " · " + stepMatch[1] + "步" : "";
  if (variant === "gaussian") {
    if (name.indexOf("clipped") >= 0 || name.indexOf("downsample") >= 0) {
      return "3DGaussian" + stepText + " · 裁切/下采样";
    }
    return "3DGaussian" + stepText + " · 原始";
  }
  if (variant === "downsampled") {
    return "Spann3R · 下采样";
  }
  if (variant === "train") {
    return "Spann3R · 训练输入";
  }
  if (variant === "raw") {
    return "Spann3R · 原始";
  }
  return variant || "其他";
}

function normalizePointcloudItem(item, dashboardUrl, typeTextFn) {
  const obj = toObject(item);
  const sizeValue = Number(obj.size_bytes);
  const downloadUrl = toDashboardAbsoluteUrl(obj.download_url || "", dashboardUrl);
  const scene = obj.scene || "-";
  const encodedScene = scene && scene !== "-" ? encodeURIComponent(scene) : "";
  const prefer = obj.variant || "gaussian";
  const sceneBaseUrl = encodedScene ?
    toDashboardAbsoluteUrl("/download/scene/" + encodedScene + "?prefer=" + prefer, dashboardUrl) :
    downloadUrl;
  const labelFn = typeof typeTextFn === "function" ? typeTextFn : inferPointcloudType;
  return {
    id: obj.id || "",
    scene: scene,
    variant: obj.variant || "other",
    typeText: labelFn(obj),
    name: obj.name || "-",
    sizeText: Number.isFinite(sizeValue) ? formatBytes(sizeValue) : "-",
    mtime: obj.mtime || "-",
    optimizedUrl: withQuery(sceneBaseUrl, "processed=true"),
    downloadUrl: downloadUrl,
    rawUrl: withQuery(sceneBaseUrl, "processed=false"),
    zipUrl: toDashboardAbsoluteUrl("/download/zip?ids=" + (obj.id || ""), dashboardUrl),
    pathText: clipText(obj.path || "", 90)
  };
}

function buildUploadStatsText(data) {
  const obj = toObject(data);
  const fileCount = pickNumber(obj, ["uploaded_files", "files", "file_count", "count", "total_files"]);
  const byteCount = pickNumber(obj, ["uploaded_bytes", "bytes", "byte_count", "total_bytes"]);
  const fileText = fileCount === null ? "文件数: -" : "文件数: " + fileCount;
  const byteText = byteCount === null ? "字节数: -" : "字节数: " + formatBytes(byteCount);
  return fileText + " | " + byteText;
}

function buildUploadsSummaryText(data) {
  const obj = toObject(data);
  const count = pickNumber(obj, ["count"]);
  const latestMtime = pickString(obj, ["latest_mtime"]);
  const watchDir = pickString(obj, ["watch_dir"]);
  const countText = count === null ? "count:-" : "count:" + count;
  const mtimeText = latestMtime ? "latest:" + latestMtime : "latest:-";
  const dirText = watchDir ? "dir:" + watchDir : "dir:-";
  return countText + " | " + mtimeText + " | " + clipText(dirText, 120);
}

function buildScenesSummaryText(data) {
  const obj = toObject(data);
  const latestScene = pickString(obj, ["latest_scene"]);
  const datasetCount = pickNumber(obj, ["dataset_count"]);
  const photoSceneCount = pickNumber(obj, ["photo_scene_count"]);
  const pointcloudCount = pickNumber(obj, ["pointcloud_count"]);
  const sceneText = latestScene ? "latest:" + latestScene : "latest:-";
  const dsText = datasetCount === null ? "dataset:-" : "dataset:" + datasetCount;
  const photoText = photoSceneCount === null ? "photo:-" : "photo:" + photoSceneCount;
  const pcText = pointcloudCount === null ? "pointcloud:-" : "pointcloud:" + pointcloudCount;
  return sceneText + " | " + dsText + " | " + photoText + " | " + pcText;
}

function buildPointcloudSummary(data, dashboardUrl, typeTextFn, limit) {
  const obj = toObject(data);
  const summary = toObject(obj.summary);
  const maxItems = typeof limit === "number" ? limit : 8;
  const items = Array.isArray(obj.items) ?
    obj.items.map((item) => normalizePointcloudItem(item, dashboardUrl, typeTextFn)) :
    [];
  const count = pickNumber(summary, ["count"]);
  const totalSize = pickString(summary, ["total_size"]);
  const latest = toObject(summary.latest);
  const sceneCount = summary.scenes && typeof summary.scenes === "object" ? Object.keys(summary.scenes).length : 0;
  const countText = count === null ? "文件数:-" : "文件数:" + count;
  const sizeText = totalSize ? "总大小:" + totalSize : "总大小:-";
  const latestText = latest && latest.name ? "最新:" + latest.name : "最新:-";
  return {
    text: countText + " | " + sizeText + " | 场景:" + sceneCount + " | " + clipText(latestText, 80),
    items: items.slice(0, maxItems)
  };
}

function buildJobsData(data, statusTextFn, limit) {
  const obj = toObject(data);
  const summary = toObject(obj.summary);
  const maxItems = typeof limit === "number" ? limit : 8;
  const items = Array.isArray(obj.items) ?
    obj.items.map((item, index) => normalizeJobItem(item, index, statusTextFn)) :
    [];
  const totalCount = pickNumber(summary, ["count"]);
  const queuedCount = pickNumber(summary, ["queued"]);
  const runningCount = pickNumber(summary, ["running"]);
  const completedCount = pickNumber(summary, ["completed"]);
  const failedCount = pickNumber(summary, ["failed"]);
  const countText = totalCount === null ? "任务:-" : "任务:" + totalCount;
  const queuedText = queuedCount === null ? "排队:-" : "排队:" + queuedCount;
  const runningText = runningCount === null ? "运行:-" : "运行:" + runningCount;
  const completedText = completedCount === null ? "完成:-" : "完成:" + completedCount;
  const failedText = failedCount === null ? "失败:-" : "失败:" + failedCount;
  return {
    text: countText + " | " + queuedText + " | " + runningText + " | " + completedText + " | " + failedText,
    items: items.slice(0, maxItems)
  };
}

function buildLogsData(data, limit) {
  const obj = toObject(data);
  const lines = Array.isArray(obj.lines) ? obj.lines : [];
  const maxItems = typeof limit === "number" ? limit : 5;
  if (lines.length === 0) {
    return { text: "lines:0 | latest:-", items: [] };
  }
  const latestLine = lines[lines.length - 1];
  return {
    text: "lines:" + lines.length + " | latest:" + clipText(latestLine, 100),
    items: lines.slice(-maxItems).map((line, index) => ({
      id: String(index),
      text: clipText(line, 140)
    }))
  };
}

function parseStatus(data) {
  const obj = toObject(data);
  const pid = pickNumber(obj, ["pid"]);
  const queueLength = pickNumber(obj, ["queue_length"]);
  const activeJob = toObject(obj.active_job);
  let running = false;
  if (typeof obj.running === "boolean") {
    running = obj.running;
  } else if (pid !== null) {
    running = true;
  }
  return {
    runningText: running ? "运行中" : "未运行",
    pidText: pid === null ? "-" : String(pid),
    queueText: queueLength === null ? "等待队列:-" : "等待队列:" + queueLength,
    jobText: activeJob && activeJob.id ? activeJob.id + " | " + (activeJob.started_at || activeJob.created_at || "-") : "-"
  };
}

function parseProgress(data) {
  const obj = toObject(data);
  const phase = pickString(obj, ["phase", "stage"]);
  const step = pickString(obj, ["step"]);
  const sceneName = pickString(obj, ["scene_name"]);
  const loss = pickNumber(obj, ["loss"]);
  const uploadedImages = pickNumber(obj, ["uploaded_images"]);
  const percent = pickNumber(obj, ["percent"]);

  let percentText = "-";
  if (percent !== null) {
    let normalized = percent;
    if (normalized <= 1) {
      normalized *= 100;
    }
    percentText = normalized.toFixed(1) + "%";
  }

  return {
    phaseKey: phase || "unknown",
    stageText: phase || "-",
    stepText: step || "-",
    sceneNameText: sceneName || "-",
    lossText: loss === null ? "-" : String(loss),
    uploadedImagesText: uploadedImages === null ? "-" : String(uploadedImages),
    percentText: percentText
  };
}

function getPhaseState(phase, options) {
  const settings = toObject(options);
  const phaseKey = phase || "unknown";
  const uploadAllow = settings.uploadAllow;
  const canUpload = Boolean(settings.uploadHealthy) &&
    (typeof uploadAllow === "boolean" ? uploadAllow : canUploadByPhase(phaseKey));
  const queueEnabled = Boolean(settings.queueEnabled);
  const hasPointclouds = Boolean(settings.hasPointclouds);
  const viewerLikelyReady = phaseKey === "gaussian" || phaseKey === "export" || phaseKey === "completed";
  if (phaseKey === "input") {
    return {
      phaseKey: phaseKey,
      phaseActionHint: canUpload ? "当前为 input 阶段：上传服务就绪，可上传采集帧。" : "当前为 input 阶段，但健康检查未通过（优先检查 uu 域名 /healthz）。",
      phaseCanUpload: canUpload,
      phaseCanViewer: viewerLikelyReady,
      phaseCanDownload: false
    };
  }
  if (phaseKey === "spann3r") {
    return {
      phaseKey: phaseKey,
      phaseActionHint: "当前为 spann3r 阶段：重建处理中，上传已禁用。",
      phaseCanUpload: canUpload,
      phaseCanViewer: viewerLikelyReady,
      phaseCanDownload: false
    };
  }
  if (phaseKey === "gaussian") {
    return {
      phaseKey: phaseKey,
      phaseActionHint: canUpload && queueEnabled ? "当前为 gaussian 阶段：Viewer 可访问，新采集会进入等待队列。" : "当前为 gaussian 阶段：可访问 Viewer，Gaussian 产物可能尚在生成。",
      phaseCanUpload: canUpload,
      phaseCanViewer: viewerLikelyReady,
      phaseCanDownload: true
    };
  }
  if (phaseKey === "export") {
    return {
      phaseKey: phaseKey,
      phaseActionHint: canUpload && queueEnabled ? "当前为 export 阶段：正在导出点云，新采集会进入等待队列。" : "当前为 export 阶段：训练已结束，正在导出可下载点云。",
      phaseCanUpload: canUpload,
      phaseCanViewer: viewerLikelyReady,
      phaseCanDownload: true
    };
  }
  if (phaseKey === "completed") {
    return {
      phaseKey: phaseKey,
      phaseActionHint: canUpload && queueEnabled ? "当前为 completed 阶段：可查看结果，也可继续上传新任务。" : "当前为 completed 阶段：可访问 Viewer 与下载点云。",
      phaseCanUpload: canUpload,
      phaseCanViewer: viewerLikelyReady,
      phaseCanDownload: true
    };
  }
  if (phaseKey === "stopped" || phaseKey === "idle") {
    return {
      phaseKey: phaseKey,
      phaseActionHint: canUpload ? "当前未在训练流程中，但上传服务可用，可直接上传。" : "当前未在训练流程中，可在6008启动流程；若健康检查不通过则暂不可上传。",
      phaseCanUpload: canUpload,
      phaseCanViewer: viewerLikelyReady,
      phaseCanDownload: false
    };
  }
  if (phaseKey === "failed") {
    return {
      phaseKey: phaseKey,
      phaseActionHint: "流程执行失败，请查看后端最新日志。",
      phaseCanUpload: false,
      phaseCanViewer: false,
      phaseCanDownload: hasPointclouds
    };
  }
  return {
    phaseKey: "unknown",
    phaseActionHint: canUpload ? "阶段未知，但上传服务可用；可尝试上传。" : "阶段未知且上传服务不可用，请检查 /api/progress 与 /healthz。",
    phaseCanUpload: canUpload,
    phaseCanViewer: viewerLikelyReady,
    phaseCanDownload: false
  };
}

function buildBackendPhases(progressData, options) {
  const settings = toObject(options);
  const progress = toObject(progressData);
  const statusData = toObject(settings.statusData);
  const phase = progress.phaseKey || "unknown";
  const runningText = statusData.runningText || "-";
  const sceneText = progress.sceneNameText && progress.sceneNameText !== "-" ? progress.sceneNameText : "等待场景";
  const stepText = progress.stepText && progress.stepText !== "-" ? progress.stepText : "0";
  const percentText = progress.percentText && progress.percentText !== "-" ? progress.percentText : "0%";
  const uploadedText = progress.uploadedImagesText && progress.uploadedImagesText !== "-" ? progress.uploadedImagesText : "0";
  const downloadReady = phase === "completed" || phase === "export" || Boolean(settings.hasPointclouds);

  let uploadState = "等待";
  let uploadClass = "pending";
  let uploadDetail = settings.dashboardHealthOk ? "状态服务已连接" : "等待后端状态服务";
  const uploadAllow = settings.uploadAllow;
  const canUploadNow = Boolean(settings.uploadHealthOk) &&
    (typeof uploadAllow === "boolean" ? uploadAllow : canUploadByPhase(phase));
  if (canUploadNow) {
    uploadState = settings.queueEnabled ? "队列就绪" : "可上传";
    uploadClass = "running";
    uploadDetail = settings.queueEnabled ? "新采集会进入等待队列，" + (statusData.queueText || "等待队列:-") : "上传入口就绪，已接收 " + uploadedText + " 张";
  } else if (settings.uploadHealthOk) {
    uploadState = "已完成";
    uploadClass = "done";
    uploadDetail = "上传阶段已关闭，进入后续训练";
  } else if (settings.dashboardHealthOk) {
    uploadState = "待上传";
    uploadClass = "warn";
    uploadDetail = "状态服务正常，上传入口未就绪";
  }

  let spann3rState = "等待";
  let spann3rClass = "pending";
  let spann3rDetail = "等待上传稳定后开始";
  if (phase === "spann3r") {
    spann3rState = "运行中";
    spann3rClass = "running";
    spann3rDetail = "正在生成场景几何与相机位姿";
  } else if (phase === "gaussian" || phase === "export" || phase === "completed") {
    spann3rState = "已完成";
    spann3rClass = "done";
    spann3rDetail = sceneText;
  } else if (phase === "stopped") {
    spann3rState = "已停止";
    spann3rClass = "warn";
    spann3rDetail = "流程已停止，可重新开始";
  }

  let gaussianState = "等待";
  let gaussianClass = "pending";
  let gaussianDetail = "等待 Spann3R 输出";
  if (phase === "gaussian") {
    gaussianState = "训练中";
    gaussianClass = "running";
    gaussianDetail = "Step " + stepText + " | " + percentText;
  } else if (phase === "export") {
    gaussianState = "导出中";
    gaussianClass = "running";
    gaussianDetail = "训练完成，正在生成点云文件";
  } else if (phase === "completed") {
    gaussianState = "已完成";
    gaussianClass = "done";
    gaussianDetail = "训练与导出已结束";
  } else if (phase === "stopped") {
    gaussianState = "已停止";
    gaussianClass = "warn";
    gaussianDetail = runningText;
  }

  let completedState = "等待";
  let completedClass = "pending";
  let completedDetail = "完成后可查看 Viewer 与下载点云";
  if (phase === "completed") {
    completedState = "可查看";
    completedClass = "done";
    completedDetail = downloadReady ? "点云下载已准备" : "训练完成，等待点云列表刷新";
  } else if (phase === "gaussian" || phase === "export") {
    completedState = "生成中";
    completedClass = "running";
    completedDetail = phase === "export" ? "正在导出下载文件" : "等待 3DGaussian 输出";
  } else if (phase === "stopped") {
    completedState = "未完成";
    completedClass = "warn";
    completedDetail = "流程停止，结果可能不完整";
  } else if (phase === "failed") {
    completedState = "失败";
    completedClass = "warn";
    completedDetail = "查看最新日志定位失败原因";
  }

  return [
    { key: "upload", title: "检测上传", state: uploadState, detail: uploadDetail, statusClass: uploadClass },
    { key: "spann3r", title: "Spann3R 训练", state: spann3rState, detail: spann3rDetail, statusClass: spann3rClass },
    { key: "gaussian", title: "3DGaussian 训练", state: gaussianState, detail: gaussianDetail, statusClass: gaussianClass },
    { key: "completed", title: "训练完成", state: completedState, detail: completedDetail, statusClass: completedClass }
  ];
}

module.exports = {
  asText,
  buildBackendPhases,
  buildJobsData,
  buildLogsData,
  buildPointcloudSummary,
  buildScenesSummaryText,
  buildUploadStatsText,
  buildUploadsSummaryText,
  canCancelJobStatus,
  canUploadByPhase,
  clipText,
  formatBytes,
  getPhaseState,
  inferPointcloudType,
  jobStatusClass,
  normalizeJobItem,
  normalizePointcloudItem,
  parseProgress,
  parseStatus,
  pickNumber,
  pickString,
  toDashboardAbsoluteUrl,
  toObject,
  withQuery
};
