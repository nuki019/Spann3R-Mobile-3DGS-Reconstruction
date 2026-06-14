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
  return phase === "idle" || phase === "input" || phase === "upload" || phase === "stopped" || phase === "unknown";
}

function canCancelJobStatus(status) {
  return status === "queued" || status === "uploading" || status === "ready";
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
  const labelFn = typeof typeTextFn === "function" ? typeTextFn : function(value) { return value.variant || "other"; };
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

module.exports = {
  asText,
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
  jobStatusClass,
  normalizeJobItem,
  normalizePointcloudItem,
  pickNumber,
  pickString,
  toDashboardAbsoluteUrl,
  toObject,
  withQuery
};
