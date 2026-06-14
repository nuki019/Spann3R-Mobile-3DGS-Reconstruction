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

module.exports = {
  asText,
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
