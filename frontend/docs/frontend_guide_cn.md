# 前端接入文档（Spann3R Pipeline）

本文档面向前端开发与前后端联调，基于当前微信小程序实现整理。后端接口与流程请配合 `Spann3R 后端接口文档（中文）` 使用。

## 1. 项目定位与职责

前端定位：采集端与联调面板。

- 采集端：调用相机与 IMU，进行“稳定性 + 清晰度”双筛选，生成可上传有效帧
- 联调面板：展示 6006/6008 健康与状态，支持启动/停止流程、导出 Gaussian、复制各接口地址
- 上传职责：将有效帧以 `multipart/form-data` 上传到 `POST /upload`

前端不承担训练与重建，仅承担“输入采集 + 状态观测 + 操作入口”。

## 2. 目录与文件

- `app.json`：页面注册、网络超时、服务域名配置
- `pages/capture/*`：采集页（相机、IMU、双筛选、上传）
- `pages/preview/*`：后端状态面板 + 本地有效帧预览 + 地址复制
- `utils/oss_upload_utils.js`：后端地址、接口常量、上传实现、鉴权 token 配置

## 3. 页面与交互

### 3.1 采集页（`pages/capture/capture`）

主要能力：

- 权限引导：相机权限、相册权限
- IMU 稳定性筛选：加速度计 + 陀螺仪
- 清晰度筛选：Laplacian 方差阈值
- 有效帧统计：总帧、有效帧、模糊淘汰数
- 上传到 6006：按“`phase + 6008 /healthz` 联合判定”允许上传，上传完成后跳转状态页

关键状态字段：

- `isCapturing`、`isUploading`
- `frameCount`、`validFrameCount`、`rejectedBlurCount`
- `rejectedIMUCount`
- `isIMUStable`、`imuVariance`
- `blurScore`、`uploadProgress`

### 3.2 状态页（`pages/preview/preview`）

主要能力：

- 轮询后端状态（6006/6008）
- 展示状态指标（status/progress/summary/logs）
- 管理动作（可选 token）：开始流程、停止流程、导出 Gaussian
- 复制联调地址（上传、Viewer、管理台、各 API、下载地址）
- 本地有效帧轮播预览

## 4. 前端到后端接口映射

端口映射（当前线上网关）：

- 后端 `6006` 映射到前端访问地址：`https://u342234-nrj1-e55849b5.bjb2.seetacloud.com:8443`
- 后端 `6008` 映射到前端访问地址：`https://uu342234-nrj1-e55849b5.bjb2.seetacloud.com:8443`

## 4.1 6006（上传 / Viewer）

- `POST /upload`：上传图片（字段：`frame_file`，可选 `token`）
- `GET /healthz`：上传服务健康
- `GET /stats`：上传累计统计
- `GET /`：训练阶段 Viewer 地址（阶段复用）
- 上传路径固定为 `/upload`，前端不再探测历史遗留上传路径。
- 前端上传门控健康检查统一使用 `6008 /healthz`（即 `uu...:8443/healthz`）。

前端文件：

- 上传实现：`utils/oss_upload_utils.js`
- 上传触发：`pages/capture/capture.js -> syncToBackend`

## 4.2 6008（管理 / 状态 / 下载）

读取接口（轮询）：

- `GET /healthz`
- `GET /api/status`
- `GET /api/progress`
- `GET /api/logs?lines=200`
- `GET /api/uploads/summary`
- `GET /api/scenes/summary`

管理接口（按钮动作）：

- `POST /api/pipeline/start`
- `POST /api/pipeline/stop`
- `POST /api/gaussian/export_latest`

下载相关：

- `GET /downloads`
- `GET /files`
- `GET /download/latest?prefer=gaussian`

## 5. 鉴权对齐

按后端文档的 token 规则，前端对应两类 token：

- 上传 token：`UPLOAD_AUTH_TOKEN`（用于 `POST /upload`）
- 管理 token：`DASHBOARD_AUTH_TOKEN`（用于 dashboard 的 `POST` 接口）

配置位置：

- `utils/oss_upload_utils.js`

说明：

- 未启用鉴权时，保持空字符串即可
- 状态页支持手动输入管理 token，优先用于管理动作请求头 `X-Auth-Token`

## 6. 轮询策略

按后端联调建议分频轮询：

- 高频（2.5 秒）：`/api/status`、`/api/progress`、`6008 /healthz`、`/stats`
- 中频（5 秒）：`/api/logs?lines=200`
- 低频（10 秒）：`/api/uploads/summary`、`/api/scenes/summary`

前端显示“最近刷新时间”和“部分接口失败”提示，便于联调定位。
说明：在 `phase=spann3r/gaussian/completed` 时，`6006` 可能已切到 Viewer，`/stats` 失败属于预期现象；上传门控只看 `uu.../healthz`。

## 7. 近期修复（关键）

## 7.1 修复“清晰但只有一张照片”

问题原因：

- `camera.takePhoto` 产生的是临时路径，连续采集时可能被覆盖或失效，导致有效帧列表实际只保留极少可用图片。

修复方案：

- 在每次拍照后立刻调用 `wx.saveFile` 将临时文件转为持久文件，使用 `savedFilePath` 参与后续清晰度计算、上传、预览、存相册。
- 新增会话级清理逻辑：新一轮采集开始时清理上一次缓存文件。

对应代码：

- `pages/capture/capture.js`
  - `persistFrameFile`
  - `processCapturedFrame`
  - `clearPersistedFrames`

## 7.2 修复“6006提示框一直不消失”

问题原因：

- 6006 说明提示使用常驻渲染，影响体验。

修复方案：

- 改为条件显示，仅在初始空闲状态展示，不再全程悬浮。

对应代码：

- `pages/capture/capture.wxml`
- `pages/capture/capture.wxss`

## 7.3 上传超时与重试增强

修复方案：

- 上传开始前先做 `GET uu.../healthz` 预检，不通过时直接提示，不再等到第一帧上传时报错。
- 单帧上传增加超时控制（20s）与一次自动重试，降低偶发网络波动导致的卡住问题。

对应代码：

- `utils/oss_upload_utils.js`

## 7.4 放宽模糊阈值并恢复 IMU 判定

修复方案：

- 模糊阈值从 `10` 放宽到 `4`，降低“全部被判模糊”的概率。
- 恢复 IMU 门控：仅设备稳定时触发拍照采集。
- 上传逻辑改为“仅上传通过 IMU + 清晰度筛选的有效帧”，不再回退上传全部采集帧。

对应代码：

- `pages/capture/capture.js`
- `pages/capture/capture.wxml`

## 8. 与后端阶段流程对齐

前端对后端阶段语义约束如下：

- 阶段 A（phase=input，上传阶段）：前端调用 6006 上传
- 阶段 C（training）：6006 复用为 Viewer
- 6006 上传与 Viewer 互斥，不并发

前端状态机策略：

- 可上传：`phase ∈ {idle,input,stopped,unknown}` 且 `uu.../healthz == ok`
- `phase=spann3r`：禁用上传，显示“处理中”
- `phase=gaussian/completed` 或 `uu.../healthz != ok`：显示 Viewer 引导
- 其他情况：提示检查 `progress`/`6008 healthz` 或在 6008 启动流程

状态页通过 `status + progress` 展示当前运行态、阶段、进度、loss、上传图数、场景名等信息。

## 9. 配置项与部署注意事项

配置文件：`utils/oss_upload_utils.js`

- `UPLOAD_BASE_URL`：上传/Viewer 访问基地址（当前映射为 `u...:8443`）
- `DASHBOARD_BASE_URL`：管理/下载访问基地址（当前映射为 `uu...:8443`）
- `UPLOAD_AUTH_TOKEN` / `DASHBOARD_AUTH_TOKEN`

部署检查清单：

1. `app.json` 中域名白名单与真实后端地址一致
2. 联调时同时观察 `phase` 与 `uu...:8443/healthz`；仅当健康检查为 `ok` 才执行上传
3. 若启用 token，先验证 401 与成功分支
4. 观察轮询指标是否稳定更新
5. 若网关地址非 HTTPS，请先补齐 HTTPS 再接入真机小程序

## 10. 当前边界

- 小程序仅作为采集与管理入口，不承担重建与训练计算
- 6006 单端口复用下，上传与 Viewer 不能同时可用
- 采集质量受设备稳定性、视角覆盖、光照与参数阈值影响
