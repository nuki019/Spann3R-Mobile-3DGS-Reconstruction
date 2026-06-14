// utils/oss_upload_utils.js
// 后端接口按 6006/6008 双端口设计
// 6006：Viewer
// 6008：管理 UI、状态接口、下载接口与 /upload-proxy 上传代理

// 端口映射说明：
// 后端 6006 -> 前端访问 https://u342234-lgwc-436004b2.bjb2.seetacloud.com:8443
// 后端 6008 -> 前端访问 https://uu342234-lgwc-436004b2.bjb2.seetacloud.com:8443
const DASHBOARD_BASE_URL = "https://uu342234-lgwc-436004b2.bjb2.seetacloud.com:8443";
const VIEWER_BASE_URL = "https://u342234-lgwc-436004b2.bjb2.seetacloud.com:8443";
const UPLOAD_PROXY_BASE_URL = `${DASHBOARD_BASE_URL}/upload-proxy`;
const UPLOAD_TIMEOUT_MS = 20000;
const MAX_UPLOAD_RETRY = 1;

// 可选：如后端开启上传鉴权，请在此填 token。
const UPLOAD_AUTH_TOKEN = "";
// 可选：如后端开启管理接口鉴权，请在此填 token（用于 dashboard 的 POST 接口）。
const DASHBOARD_AUTH_TOKEN = "";

const UPLOAD_API = `${UPLOAD_PROXY_BASE_URL}/upload`;

const BACKEND_LINKS = {
  uploadApi: UPLOAD_API,
  uploadProxyHealthUrl: `${UPLOAD_PROXY_BASE_URL}/healthz`,
  uploadStatsUrl: `${UPLOAD_PROXY_BASE_URL}/stats`,
  viewerUrl: `${VIEWER_BASE_URL}/`,
  dashboardUrl: `${DASHBOARD_BASE_URL}/`,
  dashboardHealthUrl: `${DASHBOARD_BASE_URL}/healthz`,
  statusApiUrl: `${DASHBOARD_BASE_URL}/api/status`,
  progressApiUrl: `${DASHBOARD_BASE_URL}/api/progress`,
  jobsApiUrl: `${DASHBOARD_BASE_URL}/api/jobs`,
  logsApiUrl: `${DASHBOARD_BASE_URL}/api/logs?lines=200`,
  configApiUrl: `${DASHBOARD_BASE_URL}/api/config`,
  configMetaApiUrl: `${DASHBOARD_BASE_URL}/api/config_meta`,
  uploadsSummaryApiUrl: `${DASHBOARD_BASE_URL}/api/uploads/summary`,
  uploadsClearApiUrl: `${DASHBOARD_BASE_URL}/api/uploads/clear`,
  scenesSummaryApiUrl: `${DASHBOARD_BASE_URL}/api/scenes/summary`,
  pipelineStartApiUrl: `${DASHBOARD_BASE_URL}/api/pipeline/start`,
  pipelineStopApiUrl: `${DASHBOARD_BASE_URL}/api/pipeline/stop`,
  pointcloudsClearApiUrl: `${DASHBOARD_BASE_URL}/api/pointclouds/clear`,
  pointcloudsSummaryApiUrl: `${DASHBOARD_BASE_URL}/api/pointclouds/summary`,
  gaussianExportLatestApiUrl: `${DASHBOARD_BASE_URL}/api/gaussian/export_latest`,
  downloadsUrl: `${DASHBOARD_BASE_URL}/downloads`,
  filesApiUrl: `${DASHBOARD_BASE_URL}/files`,
  latestPointCloudUrl: `${DASHBOARD_BASE_URL}/download/latest?prefer=gaussian&processed=false`,
  optimizedLatestPointCloudUrl: `${DASHBOARD_BASE_URL}/download/processed/latest?prefer=gaussian`,
  gaussianZipUrl: `${DASHBOARD_BASE_URL}/download/zip?variant=gaussian`
};

function parseUploadResult(res) {
  if (!res || res.statusCode < 200 || res.statusCode >= 300) {
    return {
      ok: false,
      message: "HTTP " + (res && res.statusCode ? res.statusCode : "unknown")
    };
  }
  if (!res.data) {
    return {
      ok: true,
      message: ""
    };
  }

  var payload = res.data;
  if (typeof payload === "string") {
    try {
      payload = JSON.parse(payload);
    } catch (e) {
      // 后端返回纯文本时，HTTP 2xx 视作成功
      return {
        ok: true,
        message: ""
      };
    }
  }

  if (payload && typeof payload.code === "number") {
    if (payload.code === 200) {
      return { ok: true, message: "" };
    }
    return {
      ok: false,
      message: payload.msg || payload.message || ("业务码 " + payload.code)
    };
  }
  if (payload && typeof payload.success === "boolean") {
    return {
      ok: payload.success,
      message: payload.success ? "" : (payload.msg || payload.message || "success=false")
    };
  }
  if (payload && typeof payload.ok === "boolean") {
    return {
      ok: payload.ok,
      message: payload.ok ? "" : (payload.msg || payload.message || "ok=false")
    };
  }
  return {
    ok: true,
    message: ""
  };
}

function parseUploadServiceReadyResult(res) {
  var statusCode = res && res.statusCode ? res.statusCode : 0;
  if (statusCode < 200 || statusCode >= 300) {
    return {
      ok: false,
      message: "上传服务检查失败（6008 /upload-proxy/healthz）：HTTP " + statusCode
    };
  }
  var payload = res && res.data ? res.data : null;
  var ok = Boolean(payload && typeof payload === "object" && payload.status === "ok");
  var allowUpload = payload && typeof payload.allow_upload === "boolean" ? payload.allow_upload : true;
  if (ok && allowUpload) {
    return {
      ok: true,
      message: ""
    };
  }
  if (ok) {
    return {
      ok: false,
      message: "上传服务已连接，但当前阶段暂不接收新照片"
    };
  }
  return {
    ok: false,
    message: "上传服务检查失败（6008 /upload-proxy/healthz）：status!=ok"
  };
}

function buildUploadServiceNetworkMessage(err) {
  var errMsg = err && err.errMsg ? err.errMsg : "network fail";
  return "上传服务检查失败（6008 /upload-proxy/healthz）：" + errMsg;
}

function buildUploadSessionId() {
  return "wx_" + Date.now() + "_" + Math.random().toString(16).slice(2, 10);
}

function uploadFramesToBackend(frameList, progressCallback, resultCallback) {
  if (!Array.isArray(frameList) || frameList.length === 0) {
    if (typeof resultCallback === "function") {
      resultCallback(false, "没有可上传的有效帧");
    }
    return;
  }

  const onProgress = typeof progressCallback === "function" ? progressCallback : function() {};
  const onResult = typeof resultCallback === "function" ? resultCallback : function() {};
  const sessionId = buildUploadSessionId();

  const checkFrameFile = function(frame) {
    return new Promise(function(resolve) {
      if (!frame || !frame.path) {
        resolve(false);
        return;
      }
      wx.getFileInfo({
        filePath: frame.path,
        success: function(info) {
          resolve(Boolean(info && info.size > 0));
        },
        fail: function() {
          resolve(false);
        }
      });
    });
  };

  const checkUploadServiceReady = function() {
    return new Promise(function(resolve) {
      wx.request({
        url: BACKEND_LINKS.uploadProxyHealthUrl,
        method: "GET",
        timeout: 5000,
        success: function(res) {
          resolve(parseUploadServiceReadyResult(res));
        },
        fail: function(err) {
          resolve({
            ok: false,
            message: buildUploadServiceNetworkMessage(err)
          });
        }
      });
    });
  };

  const uploadSingleFrame = function(frame, frameIndex) {
    return new Promise(function(resolve) {
      var header = {};
      var formData = {
        session_id: sessionId,
        frame_index: String(frameIndex),
        blur_score: frame && frame.blurScore !== undefined ? String(frame.blurScore) : "",
        imu_stable: frame && frame.imuStable !== undefined ? String(Boolean(frame.imuStable)) : "",
        captured_at: frame && frame.ts ? String(frame.ts) : ""
      };
      if (UPLOAD_AUTH_TOKEN) {
        header["X-Auth-Token"] = UPLOAD_AUTH_TOKEN;
        formData.token = UPLOAD_AUTH_TOKEN;
      }

      var attemptCount = 0;
      var tryUpload = function() {
        wx.uploadFile({
          url: BACKEND_LINKS.uploadApi,
          filePath: frame.path,
          name: "frame_file",
          header: header,
          formData: formData,
          timeout: UPLOAD_TIMEOUT_MS,
          success: function(res) {
            var result = parseUploadResult(res);
            if (result.ok) {
              resolve({
                ok: true,
                message: ""
              });
              return;
            }

            var statusCode = res && res.statusCode ? res.statusCode : 0;
            var detail = result.message || "服务端返回失败";
            console.warn("uploadFile业务失败", {
              statusCode: statusCode,
              data: res && res.data,
              filePath: frame && frame.path ? frame.path : "",
              url: BACKEND_LINKS.uploadApi
            });

            if (statusCode === 401 || statusCode === 403) {
              resolve({
                ok: false,
                message: detail + "（鉴权失败，请检查 token）"
              });
              return;
            }

            if (statusCode === 404) {
              resolve({
                ok: false,
                message: "上传接口404：6008 已连通，但 /upload-proxy/upload 不存在或未转发。请更新并重启后端 dashboard，确认 /upload-proxy/healthz 返回 ok。"
              });
              return;
            }

            if (attemptCount < MAX_UPLOAD_RETRY) {
              attemptCount += 1;
              tryUpload();
              return;
            }
            resolve({
              ok: false,
              message: detail
            });
          },
          fail: function(err) {
            var errMsg = err && err.errMsg ? err.errMsg : "network fail";
            console.warn("uploadFile网络失败", {
              errMsg: errMsg,
              filePath: frame && frame.path ? frame.path : "",
              url: BACKEND_LINKS.uploadApi
            });
            if (attemptCount < MAX_UPLOAD_RETRY) {
              attemptCount += 1;
              tryUpload();
              return;
            }
            resolve({
              ok: false,
              message: errMsg
            });
          }
        });
      };

      tryUpload();
    });
  };

  const uploadAllFrames = async function() {
    const uploadServiceState = await checkUploadServiceReady();
    if (!uploadServiceState.ok) {
      onResult(false, uploadServiceState.message);
      return;
    }

    const uploadQueue = [];
    let skippedCount = 0;
    for (const frame of frameList) {
      const isValid = await checkFrameFile(frame);
      if (!isValid) {
        console.warn("跳过无效帧文件", frame && frame.path ? frame.path : "unknown");
        skippedCount += 1;
        continue;
      }
      uploadQueue.push(frame);
    }

    if (uploadQueue.length === 0) {
      onResult(false, "没有可上传文件（" + skippedCount + "帧无效）");
      return;
    }

    const total = uploadQueue.length;
    let current = 0;
    for (const frame of uploadQueue) {
      const uploadResult = await uploadSingleFrame(frame, current);
      if (!uploadResult.ok) {
        var detail = uploadResult.message ? "：" + uploadResult.message : "";
        onResult(false, "第" + (current + 1) + "帧上传失败" + detail);
        return;
      }
      current += 1;
      onProgress(current, total);
    }
    if (skippedCount > 0) {
      onResult(true, "上传成功" + total + "帧，跳过无效帧" + skippedCount + "张，批次 " + sessionId);
      return;
    }
    onResult(true, "全部" + total + "帧上传成功，批次 " + sessionId);
  };

  uploadAllFrames().catch(function(err) {
    onResult(false, "上传异常：" + err.message);
  });
}

module.exports = {
  uploadFramesToBackend: uploadFramesToBackend,
  BACKEND_LINKS: BACKEND_LINKS,
  DASHBOARD_AUTH_TOKEN: DASHBOARD_AUTH_TOKEN,
  buildUploadSessionId: buildUploadSessionId,
  buildUploadServiceNetworkMessage: buildUploadServiceNetworkMessage,
  parseUploadResult: parseUploadResult,
  parseUploadServiceReadyResult: parseUploadServiceReadyResult
};
