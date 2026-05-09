# Spann3R 后端接口文档（中文）

本文档面向后端开发与前后端联调，按当前代码实现整理。

- 上传服务：`services/upload_server.py`
- 后端管理与下载：`services/backend_dashboard.py`
- 可选独立下载服务：`services/pointcloud_download_server.py`

## 1. 服务与端口

默认部署（4090 单端口复用方案）：

- `6006`：上传服务（阶段 A），训练开始后切换为 Viewer（阶段 C）
- `6008`：管理台 UI、状态接口、下载接口

推荐启动：

```bash
cd /root/autodl-tmp/Spann3R
bash start_backend_ui.sh
bash start_backend_4090.sh
```

一键重启：

```bash
cd /root/autodl-tmp/Spann3R
bash restart_backend_stack.sh
```

## 2. 鉴权说明

### 2.1 上传接口鉴权

- 环境变量：`UPLOAD_AUTH_TOKEN`
- 当该变量为空：上传接口无需 token
- 当该变量非空：`POST /upload` 需要下列任一方式传 token
  - 表单字段：`token`
  - Header：`X-Auth-Token`

### 2.2 管理接口鉴权

- 环境变量：`DASHBOARD_AUTH_TOKEN`
- 当该变量为空：管理接口可直接调用
- 当该变量非空：以下 `POST` 需要 Header `X-Auth-Token`
  - `POST /api/config`
  - `POST /api/uploads/clear`
  - `POST /api/pointclouds/clear`
  - `POST /api/pipeline/start`
  - `POST /api/pipeline/stop`
  - `POST /api/gaussian/export_latest`

## 3. 上传服务 API（端口 6006）

Base URL 示例：`http://127.0.0.1:6006`

### 3.1 GET `/`

返回服务简介。

### 3.2 GET `/healthz`

返回健康状态与保存目录。

响应示例：

```json
{
  "status": "ok",
  "save_dir": "/root/autodl-tmp/input_images"
}
```

### 3.3 GET `/stats`

返回上传累计统计。

响应示例：

```json
{
  "uploaded_files": 12,
  "uploaded_bytes": 3456789,
  "save_dir": "/root/autodl-tmp/input_images",
  "max_file_size_mb": 25
}
```

### 3.4 POST `/upload`

- `Content-Type`：`multipart/form-data`
- 表单：
  - `frame_file`（必填，`jpg/jpeg/png`）
  - `token`（可选）
- Header：
  - `X-Auth-Token`（可选，与 `token` 二选一）

成功响应：

```json
{
  "code": 200,
  "msg": "上传成功",
  "filename": "20260418110000_123456_ab12cd34.jpg",
  "bytes": 582311
}
```

常见错误码：

- `400`：文件类型不支持
- `401`：鉴权失败
- `413`：文件超过大小限制
- `500`：服务端保存失败

示例：

```bash
curl -X POST "http://127.0.0.1:6006/upload" \
  -H "X-Auth-Token: <UPLOAD_AUTH_TOKEN>" \
  -F "frame_file=@/path/to/frame.jpg"
```

## 4. 管理台与下载 API（端口 6008）

Base URL 示例：`http://127.0.0.1:6008`

### 4.1 页面路由

- `GET /`：管理台首页（HTML）
- `GET /downloads`：点云下载页（HTML）

### 4.2 健康检查

#### GET `/healthz`

响应字段：

- `status`
- `watch_dir`
- `scene_data_root`
- `test_photo_root`
- `pointcloud_roots`
- `auth_enabled`

### 4.3 状态与日志

#### GET `/api/status`

返回当前流水线进程状态。

```json
{
  "running": true,
  "pid": 12345
}
```

#### GET `/api/logs?lines=200`

- `lines` 范围会被限制到 `20~1000`

```json
{
  "lines": [
    "===== START 2026-04-18 11:20:00 =====",
    "..."
  ]
}
```

#### GET `/api/progress`

解析训练日志后的聚合进度对象，常用字段：

- `phase` / `stage`：`idle | input | spann3r | gaussian | completed | stopped`
- `step`、`loss`、`percent`
- `uploaded_images`
- `scene_name`
- `raw_points`、`downsampled_points`、`keep_ratio`
- `gaussian_raw_file`、`gaussian_clipped_file`
- `downsample_summary`、`gaussian_summary`
- `sections`（阶段状态数组）

### 4.4 配置接口

#### GET `/api/config`

返回可编辑配置值（来源 `.env.pipeline.4090`）。

#### GET `/api/config_meta`

返回：

- `editable_keys`：允许编辑的 key 列表
- `help`：每个 key 的说明

#### POST `/api/config`

请求体：

```json
{
  "values": {
    "MIN_IMG_COUNT": "60",
    "SPANN3R_KF_EVERY": "6"
  }
}
```

响应：

```json
{
  "ok": true,
  "values": {
    "MIN_IMG_COUNT": "60",
    "SPANN3R_KF_EVERY": "6"
  }
}
```

### 4.5 上传目录与场景汇总

#### GET `/api/uploads/summary`

返回上传目录摘要：`watch_dir`、`count`、`latest_mtime`、`items`。

#### POST `/api/uploads/clear`

删除上传目录图片。

```json
{
  "ok": true,
  "deleted": 128
}
```

#### GET `/api/scenes/summary`

返回场景与数据集摘要：

- `latest_scene`
- `dataset_count`
- `photo_scene_count`
- `pointcloud_count`
- `datasets`
- `photo_scenes`

### 4.6 流水线控制

#### POST `/api/pipeline/start`

启动 `pipeline.backend_4090`。

```json
{
  "ok": true,
  "pid": 23456
}
```

#### POST `/api/pipeline/stop`

停止当前流水线。

```json
{
  "ok": true,
  "stopped": true
}
```

### 4.7 点云接口（dashboard 内置）

#### GET `/files`

返回点云索引：

```json
{
  "items": [
    {
      "id": "abcdef1234567890",
      "name": "scene_x_gaussian_clipped.ply",
      "scene": "scene_x",
      "variant": "gaussian",
      "path": "/root/autodl-tmp/gs_train/scenes/scene_x/scene_x_gaussian_clipped.ply",
      "size_bytes": "12345678",
      "mtime": "2026-04-18 11:30:00",
      "download_url": "/download/abcdef1234567890"
    }
  ]
}
```

#### GET `/download/latest?prefer=gaussian`

按偏好下载最新点云，`prefer` 可选：

- `gaussian`
- `downsampled`
- `train`
- `raw`
- `any`

#### GET `/download/{file_id}`

按文件 ID 下载。

### 4.8 手动触发 Gaussian 导出

#### POST `/api/gaussian/export_latest`

基于最新场景执行 Gaussian 导出与裁切，返回导出路径。

```json
{
  "ok": true,
  "scene": "scene_20260418_xxxx",
  "gaussian_file": "/root/.../scene_x_gaussian_clipped.ply"
}
```

## 5. 可选独立下载服务（pointcloud_download_server.py）

当你单独启动此服务时，接口为：

- `GET /`
- `GET /healthz`
- `GET /files`
- `GET /download/latest?prefer=gaussian`
- `GET /download/{file_id}`

默认端口由 `POINTCLOUD_PORT` 控制（默认 `6008`）。

## 6. 联调建议

1. 启动后先测健康：

```bash
curl http://127.0.0.1:6008/healthz
curl http://127.0.0.1:6006/healthz
```

2. 上传压测前明确 `UPLOAD_MAX_FILE_SIZE_MB`。
3. 若启用 token，先验证 `401` 分支是否生效。
4. 前端轮询建议：
   - 高频：`/api/status`、`/api/progress`（2~3 秒）
   - 低频：`/api/scenes/summary`、`/api/logs`（5~10 秒）
