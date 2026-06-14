const app = getApp();
const { BACKEND_LINKS, DASHBOARD_AUTH_TOKEN } = require("../../utils/oss_upload_utils");
const previewState = require("../../utils/preview_state_model");

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
    jobsApiUrl: BACKEND_LINKS.jobsApiUrl,
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
    jobsSummaryText: "-",
    jobList: [],
    jobsError: "",
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
    return previewState.buildUploadStatsText(data);
  },

  buildUploadsSummaryText(data) {
    return previewState.buildUploadsSummaryText(data);
  },

  buildScenesSummaryText(data) {
    return previewState.buildScenesSummaryText(data);
  },

  toDashboardAbsoluteUrl(pathOrUrl) {
    return previewState.toDashboardAbsoluteUrl(pathOrUrl, this.data.dashboardUrl);
  },

  withQuery(url, query) {
    return previewState.withQuery(url, query);
  },

  inferPointcloudType(obj) {
    return previewState.inferPointcloudType(obj);
  },

  normalizePointcloudItem(item) {
    return previewState.normalizePointcloudItem(item, this.data.dashboardUrl);
  },

  buildPointcloudSummary(data) {
    return previewState.buildPointcloudSummary(data, this.data.dashboardUrl);
  },

  jobStatusText(status) {
    return previewState.jobStatusText(status);
  },

  jobStatusClass(status) {
    return previewState.jobStatusClass(status);
  },

  normalizeJobItem(item, index) {
    return previewState.normalizeJobItem(item, index);
  },

  buildJobsData(data) {
    return previewState.buildJobsData(data);
  },

  parseStatus(data) {
    return previewState.parseStatus(data);
  },

  canUploadByPhase(phase) {
    return previewState.canUploadByPhase(phase);
  },

  getPhaseState(phase, uploadHealthy, dashboardHealthy, uploadAllow, queueEnabled) {
    return previewState.getPhaseState(phase, {
      uploadHealthy: uploadHealthy,
      dashboardHealthy: dashboardHealthy,
      uploadAllow: uploadAllow,
      queueEnabled: queueEnabled,
      hasPointclouds: this.data.pointcloudList.length > 0
    });
  },

  parseProgress(data) {
    return previewState.parseProgress(data);
  },

  buildBackendPhases(progressData, uploadHealthOk, dashboardHealthOk, statusData, uploadAllow, queueEnabled) {
    return previewState.buildBackendPhases(progressData, {
      uploadHealthOk: uploadHealthOk,
      dashboardHealthOk: dashboardHealthOk,
      statusData: statusData,
      uploadAllow: uploadAllow,
      queueEnabled: queueEnabled,
      hasPointclouds: this.data.pointcloudList.length > 0
    });
  },

  buildLogsData(data) {
    return previewState.buildLogsData(data);
  },

  refreshFast() {
    return Promise.allSettled([
      this.requestGet(this.data.dashboardHealthUrl),
      this.requestGet(this.data.uploadProxyHealthUrl),
      this.requestGet(this.data.uploadStatsUrl),
      this.requestGet(this.data.statusApiUrl),
      this.requestGet(this.data.progressApiUrl)
    ]).then((resultList) => {
      const pollData = previewState.buildFastPollData(resultList, {
        hasPointclouds: this.data.pointcloudList.length > 0
      });
      this.fastPollFailed = pollData.failed;
      this.syncBackendError();

      this.setData(Object.assign({}, pollData.data, {
        lastUpdatedAt: formatTime(Date.now())
      }));
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
      const pollData = previewState.buildMediumPollData(resultList);

      this.mediumPollFailed = pollData.failed;
      this.syncBackendError();

      this.setData(Object.assign({}, pollData.data, {
        lastUpdatedAt: formatTime(Date.now())
      }));
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
      this.requestGet(this.data.pointcloudsSummaryApiUrl),
      this.requestGet(this.data.jobsApiUrl)
    ]).then((resultList) => {
      const pollData = previewState.buildSlowPollData(resultList, {
        dashboardUrl: this.data.dashboardUrl
      });

      this.slowPollFailed = pollData.failed;
      this.syncBackendError();

      this.setData(Object.assign({}, pollData.data, {
        lastUpdatedAt: formatTime(Date.now())
      }));
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
      const result = previewState.buildActionSuccessData(actionName, resData);
      if (!result.ok) {
        throw new Error(result.error);
      }
      this.setData({
        actionMessage: result.actionMessage
      });
      wx.showToast({
        title: result.toastTitle,
        icon: "success"
      });
      this.refreshNow();
    }).catch((err) => {
      const result = previewState.buildActionFailureData(actionName, err);
      this.setData({
        actionMessage: result.actionMessage
      });
      wx.showToast({
        title: result.toastTitle,
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

  cancelJob(e) {
    if (this.data.isActionRunning) {
      return;
    }
    const dataset = e && e.currentTarget && e.currentTarget.dataset ? e.currentTarget.dataset : {};
    const jobId = dataset.id || "";
    if (!jobId) {
      wx.showToast({ title: "任务ID为空", icon: "none" });
      return;
    }
    wx.showModal({
      title: "取消排队任务",
      content: "确认取消任务 " + jobId + "？",
      success: (res) => {
        if (!res.confirm) {
          return;
        }
        const token = (this.data.dashboardToken || "").trim();
        const url = this.data.jobsApiUrl.replace(/\/$/, "") + "/" + encodeURIComponent(jobId) + "/cancel";
        this.setData({
          isActionRunning: true,
          actionMessage: "取消任务中..."
        });
        this.requestPost(url, {}, token).then((resData) => {
          const result = previewState.buildActionSuccessData("取消任务", resData);
          if (!result.ok) {
            throw new Error(result.error);
          }
          const successData = previewState.buildCancelSuccessData(jobId);
          this.setData({
            actionMessage: successData.actionMessage
          });
          wx.showToast({
            title: successData.toastTitle,
            icon: "success"
          });
          this.refreshNow();
        }).catch((err) => {
          const result = previewState.buildCancelFailureData(err);
          this.setData({
            actionMessage: result.actionMessage
          });
          wx.showToast({
            title: result.toastTitle,
            icon: "none"
          });
        }).finally(() => {
          this.setData({
            isActionRunning: false
          });
        });
      }
    });
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

  copyConfiguredUrl(key) {
    const target = previewState.buildCopyLinkTarget(this.data, key);
    this.copyText(target.content, target.label);
  },

  copyDatasetUrl(e, label) {
    this.copyText(previewState.pickDatasetUrl(e), label);
  },

  copyUploadApiUrl() {
    this.copyConfiguredUrl("uploadApi");
  },

  copyViewerUrl() {
    this.copyConfiguredUrl("viewerUrl");
  },

  copyDashboardUrl() {
    this.copyConfiguredUrl("dashboardUrl");
  },

  copyStatusApiUrl() {
    this.copyConfiguredUrl("statusApiUrl");
  },

  copyProgressApiUrl() {
    this.copyConfiguredUrl("progressApiUrl");
  },

  copyLogsApiUrl() {
    this.copyConfiguredUrl("logsApiUrl");
  },

  copyPipelineStartApiUrl() {
    this.copyConfiguredUrl("pipelineStartApiUrl");
  },

  copyPipelineStopApiUrl() {
    this.copyConfiguredUrl("pipelineStopApiUrl");
  },

  copyGaussianExportApiUrl() {
    this.copyConfiguredUrl("gaussianExportLatestApiUrl");
  },

  copyDownloadsUrl() {
    this.copyConfiguredUrl("downloadsUrl");
  },

  copyLatestPointCloudUrl() {
    this.copyConfiguredUrl("latestPointCloudUrl");
  },

  copyOptimizedLatestPointCloudUrl() {
    this.copyConfiguredUrl("optimizedLatestPointCloudUrl");
  },

  copyGaussianZipUrl() {
    this.copyConfiguredUrl("gaussianZipUrl");
  },

  copyPointcloudDownloadUrl(e) {
    this.copyDatasetUrl(e, "优化后点云地址");
  },

  copyPointcloudRawUrl(e) {
    this.copyDatasetUrl(e, "原始点云地址");
  },

  copyPointcloudZipUrl(e) {
    this.copyDatasetUrl(e, "单文件ZIP地址");
  },

  goBack() {
    wx.navigateBack();
  }
});
