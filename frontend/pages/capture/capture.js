const app = getApp();
const { uploadFramesToBackend, BACKEND_LINKS } = require("../../utils/oss_upload_utils");

// IMU筛选配置
var IMU_CONFIG = {
  threshold: 0.8,
  gyroThreshold: 0.5,
  timeRange: 50,
  sampleInterval: "game",
  captureInterval: 350,
  calcRecentCount: 4,
  stableContinuousCount: 2
};

// 模糊度筛选配置（Laplacian 方差）
var BLUR_CONFIG = {
  threshold: 4,
  targetWidth: 128,
  maxHeight: 128,
  sampleStep: 3
};

Page({
  data: {
    hasCameraAuth: false,
    isCapturing: false,
    isUploading: false,
    uploadDone: false,
    uploadError: false,
    frameCount: 0,
    validFrameCount: 0,
    hasValidFrames: false,
    saveToAlbumDone: false,
    frameList: [],
    validFrameList: [],
    rejectedBlurCount: 0,
    rejectedIMUCount: 0,
    blurScore: 0,
    blurThreshold: BLUR_CONFIG.threshold,
    // IMU相关
    isIMUStable: false,
    imuVariance: 0,
    accX: 0,
    accY: 0,
    accZ: 0,
    gyroX: 0,
    gyroY: 0,
    gyroZ: 0,
    uploadProgress: 0,
    debugInfo: "",
    saveFailCount: 0,
    blurFallbackCount: 0,
    currentPhase: "unknown",
    phaseText: "未知",
    phaseAllowUpload: false,
    backendStatusLabel: "等待服务",
    backendStatusClass: "idle",
    uploadBlockLabel: "等待服务",
    uploadHealthOk: false,
    dashboardHealthOk: false,
    phaseHint: "正在获取后端阶段和上传服务状态..."
  },
  cameraCtx: null,
  captureTimer: null,
  imuDataCache: [],
  stableHistory: [],
  frameListCache: [],
  validFrameListCache: [],
  isProcessingFrame: false,
  imuStarted: false,
  persistedFramePaths: [],
  saveFailCounter: 0,
  blurFallbackCounter: 0,
  phasePollTimer: null,

  onLoad: function() {
    var that = this;
    wx.getSetting({
      success: function(res) {
        if (res.authSetting["scope.camera"]) {
          that.setData({ hasCameraAuth: true });
          that.initCameraContext();
          that.initIMUSensor();
        } else {
          that.setData({ hasCameraAuth: false });
        }
      },
      fail: function() {
        that.setData({ hasCameraAuth: false });
      }
    });
    this.startPhasePolling();
  },

  onShow: function() {
    if (this.data.hasCameraAuth) {
      this.initCameraContext();
      this.initIMUSensor();
    }
    this.startPhasePolling();
  },

  onHide: function() {
    if (this.data.isCapturing) {
      this.stopAllCapture({ saveToAlbum: false });
    }
    this.stopIMUSensor();
    this.stopPhasePolling();
  },

  onUnload: function() {
    this.stopAllCapture({ saveToAlbum: false });
    this.stopIMUSensor();
    this.stopPhasePolling();
  },

  getPhaseFromProgress: function(progressData) {
    var data = progressData || {};
    var phase = "";
    if (typeof data.phase === "string" && data.phase) {
      phase = data.phase;
    } else if (typeof data.stage === "string" && data.stage) {
      phase = data.stage;
    }
    return phase || "unknown";
  },

  getPhaseText: function(phase) {
    var phaseMap = {
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
  },

  getPhaseHint: function(phase, uploadHealthy, dashboardHealthy) {
    if (phase === "spann3r") {
      return "Spann3R 重建处理中，上传已禁用";
    }
    if (phase === "gaussian" || phase === "export" || phase === "completed") {
      return "当前6006通常为 Viewer 阶段，上传不可用";
    }
    if (this.isUploadAllowed(phase, uploadHealthy, dashboardHealthy)) {
      return "上传服务就绪，可调用 /upload";
    }
    if (this.canUploadByPhase(phase) && dashboardHealthy && !uploadHealthy) {
      return "状态服务已连通，但上传代理未就绪（检查 /upload-proxy/healthz）";
    }
    if (this.canUploadByPhase(phase) && !dashboardHealthy) {
      return "健康检查未通过（请检查 uu 域名 /healthz）";
    }
    if (phase === "idle" || phase === "stopped") {
      return "可在6008启动流程；若健康检查为 ok 也可直接上传";
    }
    return "后端阶段未知，请检查 /api/progress 与 /healthz";
  },

  canUploadByPhase: function(phase) {
    return phase === "idle" || phase === "input" || phase === "upload" || phase === "stopped" || phase === "unknown";
  },

  isUploadAllowed: function(phase, uploadHealthy, dashboardHealthy) {
    return this.canUploadByPhase(phase) && Boolean(uploadHealthy);
  },

  getBackendStatusLabel: function(phase, uploadHealthy, dashboardHealthy) {
    if (this.isUploadAllowed(phase, uploadHealthy, dashboardHealthy)) {
      return "后端就绪";
    }
    if (!uploadHealthy && !dashboardHealthy) {
      return "等待服务";
    }
    if (this.canUploadByPhase(phase) && !uploadHealthy) {
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
  },

  getBackendStatusClass: function(phase, uploadHealthy, dashboardHealthy) {
    if (this.isUploadAllowed(phase, uploadHealthy, dashboardHealthy)) {
      return "ok";
    }
    if (!uploadHealthy && !dashboardHealthy) {
      return "idle";
    }
    if (this.canUploadByPhase(phase) && !uploadHealthy) {
      return "warn";
    }
    if (phase === "spann3r" || phase === "gaussian" || phase === "export" || phase === "failed") {
      return "warn";
    }
    return "idle";
  },

  getUploadBlockLabel: function(phase, uploadHealthy, dashboardHealthy) {
    if (!uploadHealthy && !dashboardHealthy) {
      return "等待服务";
    }
    if (this.canUploadByPhase(phase) && !uploadHealthy) {
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
  },

  applyPhaseState: function(phase, uploadHealthy, dashboardHealthy) {
    var normalizedPhase = phase || "unknown";
    var healthOk = Boolean(uploadHealthy);
    var dashboardOk = Boolean(dashboardHealthy);
    this.setData({
      currentPhase: normalizedPhase,
      phaseText: this.getPhaseText(normalizedPhase),
      phaseAllowUpload: this.isUploadAllowed(normalizedPhase, healthOk, dashboardOk),
      backendStatusLabel: this.getBackendStatusLabel(normalizedPhase, healthOk, dashboardOk),
      backendStatusClass: this.getBackendStatusClass(normalizedPhase, healthOk, dashboardOk),
      uploadBlockLabel: this.getUploadBlockLabel(normalizedPhase, healthOk, dashboardOk),
      uploadHealthOk: healthOk,
      dashboardHealthOk: dashboardOk,
      phaseHint: this.getPhaseHint(normalizedPhase, healthOk, dashboardOk)
    });
  },

  requestProgressPhase: function() {
    var that = this;
    return new Promise(function(resolve, reject) {
      wx.request({
        url: BACKEND_LINKS.progressApiUrl,
        method: "GET",
        timeout: 5000,
        success: function(res) {
          if (res.statusCode < 200 || res.statusCode >= 300) {
            reject(new Error("HTTP " + res.statusCode));
            return;
          }
          var phase = that.getPhaseFromProgress(res.data || {});
          resolve(phase);
        },
        fail: function(err) {
          reject(err);
        }
      });
    });
  },

  requestDashboardHealth: function() {
    return new Promise(function(resolve, reject) {
      wx.request({
        url: BACKEND_LINKS.dashboardHealthUrl,
        method: "GET",
        timeout: 5000,
        success: function(res) {
          var statusCode = res && res.statusCode ? res.statusCode : 0;
          if (statusCode < 200 || statusCode >= 300) {
            resolve(false);
            return;
          }
          var payload = res && res.data ? res.data : null;
          var ok = Boolean(payload && typeof payload === "object" && payload.status === "ok");
          resolve(ok);
        },
        fail: function(err) {
          reject(err);
        }
      });
    });
  },

  requestUploadProxyHealth: function() {
    return new Promise(function(resolve, reject) {
      wx.request({
        url: BACKEND_LINKS.uploadProxyHealthUrl,
        method: "GET",
        timeout: 5000,
        success: function(res) {
          var statusCode = res && res.statusCode ? res.statusCode : 0;
          if (statusCode < 200 || statusCode >= 300) {
            resolve(false);
            return;
          }
          var payload = res && res.data ? res.data : null;
          var ok = Boolean(payload && typeof payload === "object" && payload.status === "ok");
          resolve(ok);
        },
        fail: function(err) {
          reject(err);
        }
      });
    });
  },

  refreshPhaseState: function(isSilent) {
    var that = this;
    return Promise.allSettled([
      this.requestProgressPhase(),
      this.requestDashboardHealth(),
      this.requestUploadProxyHealth()
    ]).then(function(resultList) {
      var phase = resultList[0].status === "fulfilled" ? resultList[0].value : "unknown";
      var dashboardHealthy = resultList[1].status === "fulfilled" ? resultList[1].value : false;
      var uploadHealthy = resultList[2].status === "fulfilled" ? resultList[2].value : false;
      that.applyPhaseState(phase, uploadHealthy, dashboardHealthy);
      return {
        phase: phase,
        uploadHealthy: uploadHealthy,
        dashboardHealthy: dashboardHealthy,
        phaseAllowUpload: that.isUploadAllowed(phase, uploadHealthy, dashboardHealthy)
      };
    }).catch(function() {
      if (!isSilent) {
        that.applyPhaseState("unknown", false, false);
      }
      return {
        phase: "unknown",
        uploadHealthy: false,
        dashboardHealthy: false,
        phaseAllowUpload: false
      };
    });
  },

  startPhasePolling: function() {
    var that = this;
    this.stopPhasePolling();
    this.refreshPhaseState();
    this.phasePollTimer = setInterval(function() {
      that.refreshPhaseState(true);
    }, 3000);
  },

  stopPhasePolling: function() {
    if (this.phasePollTimer) {
      clearInterval(this.phasePollTimer);
      this.phasePollTimer = null;
    }
  },

  applyCameraAuth: function() {
    var that = this;
    wx.authorize({
      scope: "scope.camera",
      success: function() {
        that.setData({ hasCameraAuth: true });
        that.initCameraContext();
        that.initIMUSensor();
        wx.showToast({ title: "相机授权成功", icon: "success" });
      },
      fail: function() {
        wx.showModal({
          title: "权限提示",
          content: "必须授权相机才能使用，请前往设置开启",
          confirmText: "去设置",
          success: function(res) {
            if (!res.confirm) {
              return;
            }
            wx.openSetting({
              success: function(setRes) {
                if (setRes.authSetting["scope.camera"]) {
                  that.setData({ hasCameraAuth: true });
                  that.initCameraContext();
                  that.initIMUSensor();
                }
              }
            });
          }
        });
      }
    });
  },

  applyAlbumAuth: function() {
    wx.authorize({
      scope: "scope.writePhotosAlbum",
      success: function() {
        wx.showToast({ title: "相册授权成功", icon: "success" });
      },
      fail: function() {
        wx.showModal({
          title: "权限提示",
          content: "授权相册才能保存关键帧，请前往设置开启",
          confirmText: "去设置",
          success: function(res) {
            if (!res.confirm) {
              return;
            }
            wx.openSetting();
          }
        });
      }
    });
  },

  initIMUSensor: function() {
    var that = this;
    if (this.imuStarted) {
      return;
    }
    this.imuStarted = true;
    this.imuDataCache = [];
    this.stableHistory = [];

    wx.startAccelerometer({
      interval: IMU_CONFIG.sampleInterval,
      success: function() {
        wx.onAccelerometerChange(function(res) {
          that.setData({
            accX: res.x.toFixed(3),
            accY: res.y.toFixed(3),
            accZ: res.z.toFixed(3)
          });
          that.imuDataCache.push({
            ts: Date.now(),
            type: "accelerometer",
            x: res.x,
            y: res.y,
            z: res.z
          });
          if (that.imuDataCache.length > 30) {
            that.imuDataCache.shift();
          }
          that.updateIMUStableStatus();
        });
      },
      fail: function() {
        that.imuStarted = false;
        wx.showToast({ title: "IMU传感器不可用", icon: "none", duration: 3000 });
      }
    });

    wx.startGyroscope({
      interval: IMU_CONFIG.sampleInterval,
      complete: function() {
        wx.onGyroscopeChange(function(res) {
          that.setData({
            gyroX: res.x.toFixed(3),
            gyroY: res.y.toFixed(3),
            gyroZ: res.z.toFixed(3)
          });
          that.updateIMUStableStatus();
        });
      }
    });
  },

  updateIMUStableStatus: function() {
    var imuVar = this.calcIMUVariance(this.imuDataCache);
    var gyroX = Number(this.data.gyroX) || 0;
    var gyroY = Number(this.data.gyroY) || 0;
    var gyroZ = Number(this.data.gyroZ) || 0;
    var isGyroStable = Math.abs(gyroX) < IMU_CONFIG.gyroThreshold &&
      Math.abs(gyroY) < IMU_CONFIG.gyroThreshold &&
      Math.abs(gyroZ) < IMU_CONFIG.gyroThreshold;
    var isAccStable = imuVar < IMU_CONFIG.threshold;

    this.stableHistory.push(isAccStable && isGyroStable);
    if (this.stableHistory.length > IMU_CONFIG.stableContinuousCount) {
      this.stableHistory.shift();
    }
    var finalStable = this.stableHistory.length === IMU_CONFIG.stableContinuousCount &&
      this.stableHistory.every(function(v) { return v === true; });

    this.setData({
      imuVariance: imuVar,
      isIMUStable: finalStable
    });
  },

  stopIMUSensor: function() {
    if (!this.imuStarted) {
      return;
    }
    wx.stopAccelerometer();
    wx.stopGyroscope();
    wx.offAccelerometerChange();
    wx.offGyroscopeChange();
    this.imuDataCache = [];
    this.stableHistory = [];
    this.imuStarted = false;
  },

  initCameraContext: function() {
    try {
      this.cameraCtx = wx.createCameraContext();
    } catch (e) {
      this.cameraCtx = null;
      this.setData({ isCapturing: false });
      wx.showToast({ title: "相机初始化失败：" + e.message, icon: "none" });
    }
  },

  toggleCapture: function() {
    if (this.data.isCapturing) {
      this.stopAllCapture();
      return;
    }
    this.startCapture();
  },

  startCapture: function() {
    var that = this;
    if (!this.cameraCtx) {
      this.initCameraContext();
    }
    if (!this.cameraCtx) {
      wx.showToast({ title: "相机未就绪", icon: "none" });
      return;
    }

    this.frameListCache = [];
    this.validFrameListCache = [];
    this.isProcessingFrame = false;
    this.saveFailCounter = 0;
    this.blurFallbackCounter = 0;
    this.clearPersistedFrames();
    app.globalData.frameList = [];
    app.globalData.validFrameList = [];

    this.setData({
      isCapturing: true,
      isUploading: false,
      uploadDone: false,
      uploadError: false,
      saveToAlbumDone: false,
      frameCount: 0,
      validFrameCount: 0,
      rejectedBlurCount: 0,
      rejectedIMUCount: 0,
      hasValidFrames: false,
      blurScore: 0,
      uploadProgress: 0,
      debugInfo: "采集已开始",
      saveFailCount: 0,
      blurFallbackCount: 0
    });

    this.captureTimer = setInterval(function() {
      if (!that.data.isCapturing || that.isProcessingFrame) {
        return;
      }
      // 恢复 IMU 门控：仅设备稳定时采集
      if (!that.data.isIMUStable) {
        return;
      }

      that.isProcessingFrame = true;
      that.cameraCtx.takePhoto({
        quality: "high",
        success: function(res) {
          that.handleCapturedFrame(res.tempImagePath);
        },
        fail: function(err) {
          that.isProcessingFrame = false;
          wx.showToast({ title: "拍照失败：" + err.errMsg, icon: "none" });
        }
      });
    }, IMU_CONFIG.captureInterval);

    wx.showToast({ title: "开始IMU+模糊度双筛选", icon: "success" });
  },

  clearPersistedFrames: function() {
    var pathList = this.persistedFramePaths || [];
    for (var i = 0; i < pathList.length; i += 1) {
      var filePath = pathList[i];
      wx.removeSavedFile({
        filePath: filePath,
        complete: function() {}
      });
    }
    this.persistedFramePaths = [];
  },

  persistFrameFile: function(tempImagePath) {
    var that = this;
    return new Promise(function(resolve, reject) {
      wx.saveFile({
        tempFilePath: tempImagePath,
        success: function(res) {
          if (res && res.savedFilePath) {
            that.persistedFramePaths.push(res.savedFilePath);
            resolve(res.savedFilePath);
            return;
          }
          reject(new Error("saveFile返回路径为空"));
        },
        fail: function(err) {
          reject(err);
        }
      });
    });
  },

  calcBlurScoreWithTimeout: function(imagePath, timeoutMs) {
    var timeout = typeof timeoutMs === "number" ? timeoutMs : 1500;
    var that = this;
    return new Promise(function(resolve) {
      var finished = false;
      var timer = setTimeout(function() {
        if (finished) {
          return;
        }
        finished = true;
        that.blurFallbackCounter += 1;
        that.setData({
          blurFallbackCount: that.blurFallbackCounter,
          debugInfo: "模糊度计算超时，已回退放行"
        });
        // 超时按清晰处理，避免卡死采集循环并误淘汰全部帧
        resolve(BLUR_CONFIG.threshold + 1);
      }, timeout);

      that.calcBlurScore(imagePath).then(function(score) {
        if (finished) {
          return;
        }
        finished = true;
        clearTimeout(timer);
        resolve(score);
      }).catch(function() {
        if (finished) {
          return;
        }
        finished = true;
        clearTimeout(timer);
        that.blurFallbackCounter += 1;
        that.setData({
          blurFallbackCount: that.blurFallbackCounter,
          debugInfo: "模糊度计算异常，已回退放行"
        });
        // 计算异常时默认放行，避免真机上全部被判模糊
        resolve(BLUR_CONFIG.threshold + 1);
      });
    });
  },

  processCapturedFrameWithBlurPath: function(storePath, frameTs, frameIMU, blurPath, imuStableAtCapture) {
    var that = this;
    var settled = false;

    var commitFrame = function(score) {
      if (settled) {
        return;
      }
      settled = true;

      var blurScore = Number(score) || 0;
      var frame = {
        path: storePath,
        ts: frameTs,
        imu: frameIMU,
        imuStable: Boolean(imuStableAtCapture),
        blurScore: blurScore
      };

      that.frameListCache.push(frame);
      var imuPassed = frame.imuStable;
      var blurPassed = blurScore >= BLUR_CONFIG.threshold;
      if (!imuPassed) {
        frame.rejectReason = "imu";
      } else if (!blurPassed) {
        frame.rejectReason = "blur";
      } else {
        frame.rejectReason = "";
      }

      if (imuPassed && blurPassed) {
        that.validFrameListCache.push(frame);
      }

      app.globalData.frameList = that.frameListCache;
      app.globalData.validFrameList = that.validFrameListCache;

      var nextRejectedBlur = that.data.rejectedBlurCount;
      var nextRejectedIMU = that.data.rejectedIMUCount;
      if (!imuPassed) {
        nextRejectedIMU += 1;
      } else if (!blurPassed) {
        nextRejectedBlur += 1;
      }

      that.setData({
        frameCount: that.frameListCache.length,
        validFrameCount: that.validFrameListCache.length,
        rejectedBlurCount: nextRejectedBlur,
        rejectedIMUCount: nextRejectedIMU,
        hasValidFrames: that.validFrameListCache.length > 0,
        blurScore: blurScore,
        saveFailCount: that.saveFailCounter,
        blurFallbackCount: that.blurFallbackCounter
      });
      that.isProcessingFrame = false;
    };

    // 兜底防卡死：即便模糊度计算链路异常，也在3秒内恢复采集
    var watchdog = setTimeout(function() {
      commitFrame(BLUR_CONFIG.threshold + 1);
    }, 3000);

    this.calcBlurScoreWithTimeout(blurPath || storePath, 1500).then(function(score) {
      clearTimeout(watchdog);
      commitFrame(score);
    }).catch(function() {
      clearTimeout(watchdog);
      commitFrame(0);
    });
  },

  handleCapturedFrame: function(tempImagePath) {
    var that = this;
    var frameTs = Date.now();
    var frameIMU = this.getIMUDataByTs(frameTs);
    var imuStableAtCapture = this.data.isIMUStable;

    wx.getFileInfo({
      filePath: tempImagePath,
      success: function(info) {
        if (info && info.size > 0) {
          that.processCapturedFrameWithBlurPath(tempImagePath, frameTs, frameIMU, tempImagePath, imuStableAtCapture);
          return;
        }
        that.persistFrameFile(tempImagePath).then(function(stablePath) {
          that.processCapturedFrameWithBlurPath(stablePath, frameTs, frameIMU, tempImagePath, imuStableAtCapture);
        }).catch(function(err) {
          that.saveFailCounter += 1;
          that.setData({
            saveFailCount: that.saveFailCounter,
            debugInfo: "临时帧不可用，兜底保存失败"
          });
          console.warn("临时帧不可用，saveFile失败", err && err.errMsg ? err.errMsg : err);
          that.processCapturedFrameWithBlurPath(tempImagePath, frameTs, frameIMU, tempImagePath, imuStableAtCapture);
        });
      },
      fail: function() {
        that.persistFrameFile(tempImagePath).then(function(stablePath) {
          that.processCapturedFrameWithBlurPath(stablePath, frameTs, frameIMU, tempImagePath, imuStableAtCapture);
        }).catch(function(err) {
          that.saveFailCounter += 1;
          that.setData({
            saveFailCount: that.saveFailCounter,
            debugInfo: "临时帧检查失败，已回退原路径"
          });
          console.warn("临时帧检查失败，saveFile失败", err && err.errMsg ? err.errMsg : err);
          that.processCapturedFrameWithBlurPath(tempImagePath, frameTs, frameIMU, tempImagePath, imuStableAtCapture);
        });
      }
    });
  },

  calcBlurScore: function(imagePath) {
    return new Promise(function(resolve, reject) {
      if (typeof wx.createOffscreenCanvas !== "function") {
        resolve(BLUR_CONFIG.threshold + 1);
        return;
      }

      wx.getImageInfo({
        src: imagePath,
        success: function(info) {
          try {
            var targetWidth = BLUR_CONFIG.targetWidth;
            var targetHeight = Math.round((info.height / info.width) * targetWidth);
            targetHeight = Math.max(64, Math.min(targetHeight, BLUR_CONFIG.maxHeight));

            var canvas = wx.createOffscreenCanvas({
              type: "2d",
              width: targetWidth,
              height: targetHeight
            });
            var ctx = canvas.getContext("2d");
            var image = canvas.createImage();
            image.onload = function() {
              try {
                ctx.drawImage(image, 0, 0, targetWidth, targetHeight);
                var pixelData = ctx.getImageData(0, 0, targetWidth, targetHeight).data;
                var gray = new Float32Array(targetWidth * targetHeight);

                for (var i = 0, p = 0; i < pixelData.length; i += 4, p += 1) {
                  gray[p] = pixelData[i] * 0.299 + pixelData[i + 1] * 0.587 + pixelData[i + 2] * 0.114;
                }

                var sum = 0;
                var sumSquare = 0;
                var count = 0;
                for (var y = 1; y < targetHeight - 1; y += BLUR_CONFIG.sampleStep) {
                  var row = y * targetWidth;
                  for (var x = 1; x < targetWidth - 1; x += BLUR_CONFIG.sampleStep) {
                    var idx = row + x;
                    var lap = gray[idx - targetWidth] +
                      gray[idx - 1] +
                      gray[idx + 1] +
                      gray[idx + targetWidth] -
                      (4 * gray[idx]);
                    var val = Math.abs(lap);
                    sum += val;
                    sumSquare += val * val;
                    count += 1;
                  }
                }

                if (count === 0) {
                  resolve(0);
                  return;
                }
                var mean = sum / count;
                var variance = (sumSquare / count) - (mean * mean);
                resolve(Number(variance.toFixed(2)));
              } catch (e) {
                reject(e);
              }
            };
            image.onerror = function(err) {
              reject(err);
            };
            image.src = imagePath;
          } catch (e) {
            reject(e);
          }
        },
        fail: function(err) {
          reject(err);
        }
      });
    });
  },

  stopAllCapture: function(options) {
    options = options || {};
    var shouldSaveToAlbum = options.saveToAlbum === true;

    if (this.captureTimer) {
      clearInterval(this.captureTimer);
      this.captureTimer = null;
    }
    this.isProcessingFrame = false;
    this.setData({ isCapturing: false });

    if (!shouldSaveToAlbum) {
      return;
    }
    var validFrameList = this.validFrameListCache;
    if (validFrameList.length > 0) {
      wx.showLoading({ title: "保存清晰有效帧到相册..." });
      this.saveFramesToAlbum(validFrameList, 0);
    } else {
      wx.showToast({ title: "无清晰有效帧（设备未完全平稳）", icon: "none" });
    }
  },

  calcIMUVariance: function(imuList) {
    if (!imuList || imuList.length === 0) {
      return 0;
    }
    var accData = imuList.filter(function(item) {
      return item.type === "accelerometer";
    });
    if (accData.length === 0) {
      return 0;
    }
    var recentAcc = accData.slice(-IMU_CONFIG.calcRecentCount);

    var getVariance = function(arr) {
      var sum = arr.reduce(function(a, b) { return a + b; }, 0);
      var avg = sum / arr.length;
      var varianceSum = arr.reduce(function(a, b) {
        return a + Math.pow(b - avg, 2);
      }, 0);
      return varianceSum / arr.length;
    };

    var xArr = recentAcc.map(function(item) { return item.x; });
    var yArr = recentAcc.map(function(item) { return item.y; });
    var zArr = recentAcc.map(function(item) { return item.z; });
    var xVar = getVariance(xArr);
    var yVar = getVariance(yArr);
    var zVar = getVariance(zArr);
    return Number((((xVar + yVar + zVar) / 3).toFixed(3)));
  },

  getIMUDataByTs: function(ts) {
    var result = [];
    for (var i = 0; i < this.imuDataCache.length; i += 1) {
      var item = this.imuDataCache[i];
      if (item.ts >= ts - IMU_CONFIG.timeRange && item.ts <= ts + IMU_CONFIG.timeRange) {
        result.push(item);
      }
    }
    return result;
  },

  saveFramesToAlbum: function(frameList, index) {
    var that = this;
    if (index >= frameList.length) {
      wx.hideLoading();
      that.setData({
        saveToAlbumDone: true,
        hasValidFrames: true
      });
      wx.showToast({
        title: "清晰有效帧" + frameList.length + "张已存相册",
        icon: "success"
      });
      return;
    }
    wx.saveImageToPhotosAlbum({
      filePath: frameList[index].path,
      success: function() {
        setTimeout(function() {
          that.saveFramesToAlbum(frameList, index + 1);
        }, 80);
      },
      fail: function() {
        wx.hideLoading();
        wx.showToast({ title: "保存第" + (index + 1) + "帧失败", icon: "none" });
      }
    });
  },

  syncToBackend: function() {
    var that = this;
    if (this.data.isCapturing) {
      wx.showToast({ title: "请先停止采集再上传", icon: "none" });
      return;
    }
    if (this.data.isUploading) {
      return;
    }

    this.refreshPhaseState().then(function(state) {
      if (!state.phaseAllowUpload) {
        that.setData({
          debugInfo: "上传被阻止：phase=" + that.getPhaseText(state.phase) +
            "，healthz(uu)=" + (state.dashboardHealthy ? "ok" : "not_ok")
        });
        wx.showModal({
          title: "当前不可上传",
          content: "当前阶段：" + that.getPhaseText(state.phase) + "\n" + that.getPhaseHint(state.phase, state.uploadHealthy, state.dashboardHealthy),
          showCancel: false
        });
        return;
      }

      var validFrameList = that.validFrameListCache;
      if (validFrameList.length === 0) {
        wx.showToast({ title: "暂无通过IMU+清晰度筛选的有效帧", icon: "none" });
        return;
      }
      var uploadFrameList = validFrameList;

      that.setData({
        isUploading: true,
        uploadDone: false,
        uploadError: false,
        uploadProgress: 0,
        debugInfo: "开始上传..."
      });

      wx.showLoading({
        title: "上传到6006：0/" + uploadFrameList.length,
        mask: true
      });

      uploadFramesToBackend(
        uploadFrameList,
        function(current, total) {
          var progress = Math.floor((current / total) * 100);
          that.setData({ uploadProgress: progress });
          wx.showLoading({
            title: "上传到6006：" + current + "/" + total + " (" + progress + "%)",
            mask: true
          });
        },
        function(isSuccess, msg) {
          wx.hideLoading();
          if (isSuccess) {
            that.setData({
              isUploading: false,
              uploadDone: true,
              debugInfo: msg
            });
            wx.showToast({ title: msg, icon: "success", duration: 2000 });
            wx.navigateTo({
              url: "/pages/preview/preview",
              fail: function() {
                wx.showToast({ title: "跳转预览页失败", icon: "none" });
              }
            });
            return;
          }
          that.setData({
            isUploading: false,
            uploadError: true,
            debugInfo: msg || "上传失败"
          });
          wx.showModal({
            title: "上传失败",
            content: msg || "未知错误",
            showCancel: false
          });
        }
      );
    });
  },

  onCameraError: function(e) {
    wx.showToast({ title: "相机错误：" + e.detail.errMsg, icon: "none" });
    this.stopAllCapture({ saveToAlbum: false });
  }
});
