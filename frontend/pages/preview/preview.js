const app = getApp();
const { BACKEND_LINKS, DASHBOARD_AUTH_TOKEN } = require("../../utils/oss_upload_utils");

function formatTime(ts) {
  const date = new Date(ts);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  const h = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const s = String(date.getSeconds()).padStart(2, "0");
  return y + "-" + m + "-" + d + " " + h + ":" + mm + ":" + s;
}

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

Page({
  data: {
    validFrames: [],
    currentIndex: 0,
    uploadApi: BACKEND_LINKS.uploadApi,
    uploadProxyHealthUrl: BACKEND_LINKS.uploadProxyHealthUrl,
    viewerUrl: BACKEND_LINKS.viewerUrl,
    dashboardUrl: BACKEND_LINKS.dashboardUrl,
    uploadStatsUrl: BACKEND_LINKS.uploadStatsUrl,
    dashboardHealthUrl: BACKEND_LINKS.dashboardHealthUrl,
    statusApiUrl: BACKEND_LINKS.statusApiUrl,
    progressApiUrl: BACKEND_LINKS.progressApiUrl,
    logsApiUrl: BACKEND_LINKS.logsApiUrl,
    uploadsSummaryApiUrl: BACKEND_LINKS.uploadsSummaryApiUrl,
    scenesSummaryApiUrl: BACKEND_LINKS.scenesSummaryApiUrl,
    pipelineStartApiUrl: BACKEND_LINKS.pipelineStartApiUrl,
    pipelineStopApiUrl: BACKEND_LINKS.pipelineStopApiUrl,
    gaussianExportLatestApiUrl: BACKEND_LINKS.gaussianExportLatestApiUrl,
    downloadsUrl: BACKEND_LINKS.downloadsUrl,
    filesApiUrl: BACKEND_LINKS.filesApiUrl,
    pointcloudsSummaryApiUrl: BACKEND_LINKS.pointcloudsSummaryApiUrl,
    latestPointCloudUrl: BACKEND_LINKS.latestPointCloudUrl,
    optimizedLatestPointCloudUrl: BACKEND_LINKS.optimizedLatestPointCloudUrl,
    gaussianZipUrl: BACKEND_LINKS.gaussianZipUrl,
    copiedLabel: "",
    isRefreshing: false,
    backendError: "",
    uploadHealthText: "-",
    dashboardHealthText: "-",
    uploadStatsText: "-",
    pipelineRunningText: "-",
    pipelinePidText: "-",
    pipelineQueueText: "-",
    pipelineJobText: "-",
    backendPhases: [
      { key: "upload", title: "检测上传", state: "等待", detail: "-", statusClass: "pending" },
      { key: "spann3r", title: "Spann3R 训练", state: "等待", detail: "-", statusClass: "pending" },
      { key: "gaussian", title: "3DGaussian 训练", state: "等待", detail: "-", statusClass: "pending" },
      { key: "completed", title: "训练完成", state: "等待", detail: "-", statusClass: "pending" }
    ],
    phaseKey: "unknown",
    phaseActionHint: "等待后端阶段信息...",
    phaseCanUpload: false,
    phaseCanViewer: false,
    phaseCanDownload: false,
    pipelineStageText: "-",
    pipelineStepText: "-",
    pipelinePercentText: "-",
    pipelineLossText: "-",
    uploadedImagesText: "-",
    sceneNameText: "-",
    uploadsSummaryText: "-",
    scenesSummaryText: "-",
    pointcloudSummaryText: "-",
    pointcloudList: [],
    pointcloudError: "",
    logsSummaryText: "-",
    latestLogLines: [],
    lastUpdatedAt: "-",
    dashboardToken: DASHBOARD_AUTH_TOKEN || "",
    isActionRunning: false,
    actionMessage: ""
  },
  fastPollTimer: null,
  mediumPollTimer: null,
  slowPollTimer: null,
  fastPollFailed: false,
  mediumPollFailed: false,
  slowPollFailed: false,

  onLoad() {
    const validFrames = app.globalData.validFrameList || [];
    const frameList = app.globalData.frameList || [];
    const displayFrames = validFrames.length > 0 ? validFrames : frameList;
    this.setData({ validFrames: displayFrames });
    if (displayFrames.length === 0) {
      wx.showToast({ title: "暂无本地有效采集帧", icon: "none" });
    } else if (validFrames.length === 0 && frameList.length > 0) {
      wx.showToast({ title: "未筛出清晰帧，展示全部采集帧", icon: "none" });
    }
    this.startPolling();
  },

  onUnload() {
    this.stopPolling();
  },

  startPolling() {
    this.stopPolling();
    this.refreshNow();
    this.fastPollTimer = setInterval(() => {
      this.refreshFast();
    }, 2500);
    this.mediumPollTimer = setInterval(() => {
      this.refreshMedium();
    }, 5000);
    this.slowPollTimer = setInterval(() => {
      this.refreshSlow();
    }, 10000);
  },

  stopPolling() {
    if (this.fastPollTimer) {
      clearInterval(this.fastPollTimer);
      this.fastPollTimer = null;
    }
    if (this.mediumPollTimer) {
      clearInterval(this.mediumPollTimer);
      this.mediumPollTimer = null;
    }
    if (this.slowPollTimer) {
      clearInterval(this.slowPollTimer);
      this.slowPollTimer = null;
    }
  },

  syncBackendError() {
    const hasError = this.fastPollFailed || this.mediumPollFailed || this.slowPollFailed;
    this.setData({
      backendError: hasError ? "部分接口拉取失败，请检查后端服务、域名白名单或鉴权配置" : ""
    });
  },

  requestGet(url) {
    return new Promise((resolve, reject) => {
      wx.request({
        url: url,
        method: "GET",
        timeout: 5000,
        success: (res) => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(res.data);
            return;
          }
          reject(new Error("HTTP " + res.statusCode));
        },
        fail: (err) => reject(err)
      });
    });
  },

  requestPost(url, data, authToken) {
    const header = {
      "content-type": "application/json"
    };
    if (authToken) {
      header["X-Auth-Token"] = authToken;
    }
    return new Promise((resolve, reject) => {
      wx.request({
        url: url,
        method: "POST",
        header: header,
        data: data || {},
        timeout: 8000,
        success: (res) => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(res.data);
            return;
          }
          reject(new Error("HTTP " + res.statusCode));
        },
        fail: (err) => reject(err)
      });
    });
  },

  buildUploadStatsText(data) {
    const obj = toObject(data);
    const fileCount = pickNumber(obj, ["uploaded_files", "files", "file_count", "count", "total_files"]);
    const byteCount = pickNumber(obj, ["uploaded_bytes", "bytes", "byte_count", "total_bytes"]);
    const fileText = fileCount === null ? "文件数: -" : "文件数: " + fileCount;
    const byteText = byteCount === null ? "字节数: -" : "字节数: " + formatBytes(byteCount);
    return fileText + " | " + byteText;
  },

  buildUploadsSummaryText(data) {
    const obj = toObject(data);
    const count = pickNumber(obj, ["count"]);
    const latestMtime = pickString(obj, ["latest_mtime"]);
    const watchDir = pickString(obj, ["watch_dir"]);
    const countText = count === null ? "count:-" : "count:" + count;
    const mtimeText = latestMtime ? "latest:" + latestMtime : "latest:-";
    const dirText = watchDir ? "dir:" + watchDir : "dir:-";
    return countText + " | " + mtimeText + " | " + clipText(dirText, 120);
  },

  buildScenesSummaryText(data) {
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
  },

  toDashboardAbsoluteUrl(pathOrUrl) {
    if (!pathOrUrl) {
      return "";
    }
    if (/^https?:\/\//.test(pathOrUrl)) {
      return pathOrUrl;
    }
    const base = (this.data.dashboardUrl || "").replace(/\/$/, "");
    const path = pathOrUrl.charAt(0) === "/" ? pathOrUrl : "/" + pathOrUrl;
    return base + path;
  },

  withQuery(url, query) {
    if (!url) {
      return "";
    }
    return url + (url.indexOf("?") >= 0 ? "&" : "?") + query;
  },

  inferPointcloudType(obj) {
    const variant = (obj.variant || "other").toLowerCase();
    const name = (obj.name || "").toLowerCase();
    const path = (obj.path || "").toLowerCase();
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
  },

  normalizePointcloudItem(item) {
    const obj = toObject(item);
    const sizeValue = Number(obj.size_bytes);
    const downloadUrl = this.toDashboardAbsoluteUrl(obj.download_url || "");
    const scene = obj.scene || "-";
    const encodedScene = scene && scene !== "-" ? encodeURIComponent(scene) : "";
    const prefer = obj.variant || "gaussian";
    const sceneBaseUrl = encodedScene ? this.toDashboardAbsoluteUrl("/download/scene/" + encodedScene + "?prefer=" + prefer) : downloadUrl;
    return {
      id: obj.id || "",
      scene: scene,
      variant: obj.variant || "other",
      typeText: this.inferPointcloudType(obj),
      name: obj.name || "-",
      sizeText: Number.isFinite(sizeValue) ? formatBytes(sizeValue) : "-",
      mtime: obj.mtime || "-",
      optimizedUrl: this.withQuery(sceneBaseUrl, "processed=true"),
      downloadUrl: downloadUrl,
      rawUrl: this.withQuery(sceneBaseUrl, "processed=false"),
      zipUrl: this.toDashboardAbsoluteUrl("/download/zip?ids=" + (obj.id || "")),
      pathText: clipText(obj.path || "", 90)
    };
  },

  buildPointcloudSummary(data) {
    const obj = toObject(data);
    const summary = toObject(obj.summary);
    const items = Array.isArray(obj.items) ? obj.items.map((item) => this.normalizePointcloudItem(item)) : [];
    const count = pickNumber(summary, ["count"]);
    const totalSize = pickString(summary, ["total_size"]);
    const latest = toObject(summary.latest);
    const sceneCount = summary.scenes && typeof summary.scenes === "object" ? Object.keys(summary.scenes).length : 0;
    const countText = count === null ? "文件数:-" : "文件数:" + count;
    const sizeText = totalSize ? "总大小:" + totalSize : "总大小:-";
    const latestText = latest && latest.name ? "最新:" + latest.name : "最新:-";
    return {
      text: countText + " | " + sizeText + " | 场景:" + sceneCount + " | " + clipText(latestText, 80),
      items: items.slice(0, 8)
    };
  },

  parseStatus(data) {
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
  },

  canUploadByPhase(phase) {
    return phase === "idle" || phase === "input" || phase === "upload" || phase === "stopped" || phase === "unknown";
  },

  getPhaseState(phase, uploadHealthy, dashboardHealthy) {
    const phaseKey = phase || "unknown";
    const canUpload = this.canUploadByPhase(phaseKey) && Boolean(uploadHealthy);
    const viewerLikelyReady = phaseKey === "gaussian" || phaseKey === "export" || phaseKey === "completed";
    if (phaseKey === "input") {
      return {
        phaseKey: phaseKey,
        phaseActionHint: canUpload ? "当前为 input 阶段：上传服务就绪，可上传帧到 /upload。" : "当前为 input 阶段，但健康检查未通过（优先检查 uu 域名 /healthz）。",
        phaseCanUpload: canUpload,
        phaseCanViewer: viewerLikelyReady,
        phaseCanDownload: false
      };
    }
    if (phaseKey === "spann3r") {
      return {
        phaseKey: phaseKey,
        phaseActionHint: "当前为 spann3r 阶段：重建处理中，上传已禁用。",
        phaseCanUpload: false,
        phaseCanViewer: viewerLikelyReady,
        phaseCanDownload: false
      };
    }
    if (phaseKey === "gaussian") {
      return {
        phaseKey: phaseKey,
        phaseActionHint: "当前为 gaussian 阶段：可访问 Viewer，Gaussian 产物可能尚在生成。",
        phaseCanUpload: false,
        phaseCanViewer: viewerLikelyReady,
        phaseCanDownload: true
      };
    }
    if (phaseKey === "export") {
      return {
        phaseKey: phaseKey,
        phaseActionHint: "当前为 export 阶段：训练已结束，正在导出可下载点云。",
        phaseCanUpload: false,
        phaseCanViewer: viewerLikelyReady,
        phaseCanDownload: true
      };
    }
    if (phaseKey === "completed") {
      return {
        phaseKey: phaseKey,
        phaseActionHint: "当前为 completed 阶段：可访问 Viewer 与下载点云。",
        phaseCanUpload: false,
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
        phaseCanDownload: this.data.pointcloudList.length > 0
      };
    }
    return {
      phaseKey: "unknown",
      phaseActionHint: canUpload ? "阶段未知，但上传服务可用；可尝试上传。" : "阶段未知且上传服务不可用，请检查 /api/progress 与 /healthz。",
      phaseCanUpload: canUpload,
      phaseCanViewer: viewerLikelyReady,
      phaseCanDownload: false
    };
  },

  parseProgress(data) {
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
        normalized = normalized * 100;
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
  },

  buildBackendPhases(progressData, uploadHealthOk, dashboardHealthOk, statusData) {
    const phase = progressData.phaseKey || "unknown";
    const runningText = statusData && statusData.runningText ? statusData.runningText : "-";
    const sceneText = progressData.sceneNameText && progressData.sceneNameText !== "-" ? progressData.sceneNameText : "等待场景";
    const stepText = progressData.stepText && progressData.stepText !== "-" ? progressData.stepText : "0";
    const percentText = progressData.percentText && progressData.percentText !== "-" ? progressData.percentText : "0%";
    const uploadedText = progressData.uploadedImagesText && progressData.uploadedImagesText !== "-" ? progressData.uploadedImagesText : "0";
    const downloadReady = phase === "completed" || phase === "export" || this.data.pointcloudList.length > 0;

    let uploadState = "等待";
    let uploadClass = "pending";
    let uploadDetail = dashboardHealthOk ? "状态服务已连接" : "等待后端状态服务";
    if (uploadHealthOk && this.canUploadByPhase(phase)) {
      uploadState = "可上传";
      uploadClass = "running";
      uploadDetail = "上传入口就绪，已接收 " + uploadedText + " 张";
    } else if (uploadHealthOk) {
      uploadState = "已完成";
      uploadClass = "done";
      uploadDetail = "上传阶段已关闭，进入后续训练";
    } else if (dashboardHealthOk) {
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
  },

  buildLogsData(data) {
    const obj = toObject(data);
    const lines = Array.isArray(obj.lines) ? obj.lines : [];
    if (lines.length === 0) {
      return { text: "lines:0 | latest:-", items: [] };
    }
    const latestLine = lines[lines.length - 1];
    return {
      text: "lines:" + lines.length + " | latest:" + clipText(latestLine, 100),
      items: lines.slice(-5).map((line, index) => ({
        id: String(index),
        text: clipText(line, 140)
      }))
    };
  },

  refreshFast() {
    return Promise.allSettled([
      this.requestGet(this.data.dashboardHealthUrl),
      this.requestGet(this.data.uploadProxyHealthUrl),
      this.requestGet(this.data.uploadStatsUrl),
      this.requestGet(this.data.statusApiUrl),
      this.requestGet(this.data.progressApiUrl)
    ]).then((resultList) => {
      const dashboardHealthOk = resultList[0].status === "fulfilled" &&
        Boolean(resultList[0].value && typeof resultList[0].value === "object" && resultList[0].value.status === "ok");
      const uploadHealthOk = resultList[1].status === "fulfilled" &&
        Boolean(resultList[1].value && typeof resultList[1].value === "object" && resultList[1].value.status === "ok");
      const uploadHealth = uploadHealthOk ? "正常" : "不可用";
      const dashboardHealth = dashboardHealthOk ? "正常" : "异常";
      const uploadStats = resultList[2].status === "fulfilled" ? this.buildUploadStatsText(resultList[2].value) : "拉取失败";

      const statusData = resultList[3].status === "fulfilled" ? this.parseStatus(resultList[3].value) : {
        runningText: "拉取失败",
        pidText: "-",
        queueText: "-",
        jobText: "-"
      };
      const progressData = resultList[4].status === "fulfilled" ? this.parseProgress(resultList[4].value) : {
        phaseKey: "unknown",
        stageText: "拉取失败",
        stepText: "-",
        sceneNameText: "-",
        lossText: "-",
        uploadedImagesText: "-",
        percentText: "-"
      };
      const phaseState = this.getPhaseState(progressData.phaseKey, uploadHealthOk, dashboardHealthOk);
      const backendPhases = this.buildBackendPhases(progressData, uploadHealthOk, dashboardHealthOk, statusData);

      this.fastPollFailed = resultList[0].status === "rejected" ||
        resultList[1].status === "rejected" ||
        resultList[3].status === "rejected" ||
        resultList[4].status === "rejected";
      this.syncBackendError();

      this.setData({
        uploadHealthText: uploadHealth,
        dashboardHealthText: dashboardHealth,
        uploadStatsText: uploadStats,
        pipelineRunningText: statusData.runningText,
        pipelinePidText: statusData.pidText,
        pipelineQueueText: statusData.queueText,
        pipelineJobText: statusData.jobText,
        backendPhases: backendPhases,
        phaseKey: phaseState.phaseKey,
        phaseActionHint: phaseState.phaseActionHint,
        phaseCanUpload: phaseState.phaseCanUpload,
        phaseCanViewer: phaseState.phaseCanViewer,
        phaseCanDownload: phaseState.phaseCanDownload,
        pipelineStageText: progressData.stageText,
        pipelineStepText: progressData.stepText,
        pipelinePercentText: progressData.percentText,
        pipelineLossText: progressData.lossText,
        uploadedImagesText: progressData.uploadedImagesText,
        sceneNameText: progressData.sceneNameText,
        lastUpdatedAt: formatTime(Date.now())
      });
    }).catch(() => {
      this.fastPollFailed = true;
      this.syncBackendError();
      this.setData({ lastUpdatedAt: formatTime(Date.now()) });
    });
  },

  refreshMedium() {
    return Promise.allSettled([
      this.requestGet(this.data.logsApiUrl)
    ]).then((resultList) => {
      const logsData = resultList[0].status === "fulfilled" ? this.buildLogsData(resultList[0].value) : { text: "拉取失败", items: [] };

      this.mediumPollFailed = resultList.some((item) => item.status === "rejected");
      this.syncBackendError();

      this.setData({
        logsSummaryText: logsData.text,
        latestLogLines: logsData.items,
        lastUpdatedAt: formatTime(Date.now())
      });
    }).catch(() => {
      this.mediumPollFailed = true;
      this.syncBackendError();
      this.setData({ lastUpdatedAt: formatTime(Date.now()) });
    });
  },

  refreshSlow() {
    return Promise.allSettled([
      this.requestGet(this.data.uploadsSummaryApiUrl),
      this.requestGet(this.data.scenesSummaryApiUrl),
      this.requestGet(this.data.pointcloudsSummaryApiUrl)
    ]).then((resultList) => {
      const uploadsSummary = resultList[0].status === "fulfilled" ? this.buildUploadsSummaryText(resultList[0].value) : "拉取失败";
      const scenesSummary = resultList[1].status === "fulfilled" ? this.buildScenesSummaryText(resultList[1].value) : "拉取失败";
      const pointcloudData = resultList[2].status === "fulfilled" ? this.buildPointcloudSummary(resultList[2].value) : { text: "拉取失败", items: [] };

      this.slowPollFailed = resultList.some((item) => item.status === "rejected");
      this.syncBackendError();

      this.setData({
        uploadsSummaryText: uploadsSummary,
        scenesSummaryText: scenesSummary,
        pointcloudSummaryText: pointcloudData.text,
        pointcloudList: pointcloudData.items,
        pointcloudError: resultList[2].status === "rejected" ? "点云清单拉取失败，请检查 /api/pointclouds/summary" : "",
        lastUpdatedAt: formatTime(Date.now())
      });
    }).catch(() => {
      this.slowPollFailed = true;
      this.syncBackendError();
      this.setData({ lastUpdatedAt: formatTime(Date.now()) });
    });
  },

  runPipelineAction(apiUrl, actionName) {
    if (this.data.isActionRunning) {
      return;
    }

    const token = (this.data.dashboardToken || "").trim();
    this.setData({
      isActionRunning: true,
      actionMessage: actionName + "中..."
    });

    this.requestPost(apiUrl, {}, token).then((resData) => {
      const payload = toObject(resData);
      if (payload && payload.ok === false) {
        throw new Error(payload.msg || payload.error || "接口返回失败");
      }
      this.setData({
        actionMessage: actionName + "成功：" + asText(payload, 120)
      });
      wx.showToast({
        title: actionName + "成功",
        icon: "success"
      });
      this.refreshNow();
    }).catch((err) => {
      const errMsg = err && err.message ? err.message : "未知错误";
      this.setData({
        actionMessage: actionName + "失败：" + errMsg
      });
      wx.showToast({
        title: actionName + "失败",
        icon: "none"
      });
    }).finally(() => {
      this.setData({
        isActionRunning: false
      });
    });
  },

  startPipeline() {
    this.runPipelineAction(this.data.pipelineStartApiUrl, "启动流程");
  },

  stopPipeline() {
    this.runPipelineAction(this.data.pipelineStopApiUrl, "停止流程");
  },

  exportLatestGaussian() {
    this.runPipelineAction(this.data.gaussianExportLatestApiUrl, "导出Gaussian");
  },

  refreshNow() {
    this.setData({
      isRefreshing: true
    });

    Promise.allSettled([
      this.refreshFast(),
      this.refreshMedium(),
      this.refreshSlow()
    ]).finally(() => {
      this.setData({
        isRefreshing: false,
        lastUpdatedAt: formatTime(Date.now())
      });
    });
  },

  onDashboardTokenInput(e) {
    this.setData({
      dashboardToken: e.detail.value || ""
    });
  },

  onSwiperChange(e) {
    this.setData({ currentIndex: e.detail.current });
  },

  onImageError(e) {
    console.warn("预览图加载失败", e.detail.errMsg);
  },

  copyText(content, label) {
    wx.setClipboardData({
      data: content,
      success: () => {
        this.setData({ copiedLabel: label });
        setTimeout(() => this.setData({ copiedLabel: "" }), 2000);
      },
      fail: () => {
        wx.showToast({ title: "复制失败", icon: "none" });
      }
    });
  },

  copyUploadApiUrl() {
    this.copyText(this.data.uploadApi, "上传接口地址");
  },

  copyViewerUrl() {
    this.copyText(this.data.viewerUrl, "Viewer 地址");
  },

  copyDashboardUrl() {
    this.copyText(this.data.dashboardUrl, "后端 UI 地址");
  },

  copyStatusApiUrl() {
    this.copyText(this.data.statusApiUrl, "状态接口地址");
  },

  copyProgressApiUrl() {
    this.copyText(this.data.progressApiUrl, "进度接口地址");
  },

  copyLogsApiUrl() {
    this.copyText(this.data.logsApiUrl, "日志接口地址");
  },

  copyPipelineStartApiUrl() {
    this.copyText(this.data.pipelineStartApiUrl, "启动接口地址");
  },

  copyPipelineStopApiUrl() {
    this.copyText(this.data.pipelineStopApiUrl, "停止接口地址");
  },

  copyGaussianExportApiUrl() {
    this.copyText(this.data.gaussianExportLatestApiUrl, "Gaussian导出接口地址");
  },

  copyDownloadsUrl() {
    this.copyText(this.data.downloadsUrl, "点云下载列表地址");
  },

  copyLatestPointCloudUrl() {
    this.copyText(this.data.latestPointCloudUrl, "最新点云地址");
  },

  copyOptimizedLatestPointCloudUrl() {
    this.copyText(this.data.optimizedLatestPointCloudUrl, "优化后最新点云地址");
  },

  copyGaussianZipUrl() {
    this.copyText(this.data.gaussianZipUrl, "Gaussian打包下载地址");
  },

  copyPointcloudDownloadUrl(e) {
    const url = e && e.currentTarget && e.currentTarget.dataset ? e.currentTarget.dataset.url : "";
    this.copyText(url, "优化后点云地址");
  },

  copyPointcloudRawUrl(e) {
    const url = e && e.currentTarget && e.currentTarget.dataset ? e.currentTarget.dataset.url : "";
    this.copyText(url, "原始点云地址");
  },

  copyPointcloudZipUrl(e) {
    const url = e && e.currentTarget && e.currentTarget.dataset ? e.currentTarget.dataset.url : "";
    this.copyText(url, "单文件ZIP地址");
  },

  goBack() {
    wx.navigateBack();
  }
});
