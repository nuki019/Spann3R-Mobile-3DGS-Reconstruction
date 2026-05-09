# Spann3R + Gaussian Splatting 自动化流程文档（中文版）

## 1. 目标与流程总览

本流程用于将前端上传的图像帧，自动转为可训练的 Nerfstudio 数据并启动 `splatfacto`：

1. 前端/小程序调用 `services/upload_server.py` 上传图片到 `WATCH_DIR`  
2. `pipeline/auto_gs.py` 监听上传目录，检测“图片数量达标 + 文件稳定”  
3. `demo.py` 做 Spann3R 推理，输出 `.npy` + 双点云（`*_raw.ply`、`*_downsampled_vs{voxel}.ply`）  
4. `pipeline/spann3r_to_nerfstudio.py` 把位姿与内参转换为 `transforms.json`  
5. `ns-train splatfacto` 开始训练并在网页端（Viewer）可视化
6. 训练结束后自动执行 `ns-export gaussian-splat`，输出并裁切 Gaussian 点云

---

## 2. 关键文件职责

- `services/upload_server.py`：上传入口（分块写盘、可选 token、大小限制、健康检查）
- `pipeline/auto_gs.py`：主编排器（监听、推理、转换、数据整理、启动训练）
- `demo.py`：Spann3R 推理（含 `conf_thresh/kf_every/resolution/voxel_size`）
- `pipeline/spann3r_to_nerfstudio.py`：将 Spann3R 输出转换为 Nerfstudio `transforms.json`
- `services/backend_dashboard.py`：后端管理台与点云下载接口
- `start_all.sh`：一键启动上传服务 + 自动流水线
- `.env.pipeline.example`：流程参数模板
- `Dockerfile.pipeline` / `docker-compose.pipeline.yml`：可复用镜像方案

---

## 3. 参数分层与调优建议

### 3.1 上传层（`services/upload_server.py`）

- `UPLOAD_AUTH_TOKEN`：生产建议开启；前端带 `token` 表单字段或 `X-Auth-Token` 头
- `UPLOAD_MAX_FILE_SIZE_MB`：单帧上限，默认 `25`
- `UPLOAD_ALLOW_ORIGINS`：跨域白名单，默认 `*`

### 3.2 流水线触发层（`pipeline/auto_gs.py`）

- `MIN_IMG_COUNT`：最小触发帧数，默认 `50`
- `STABLE_POLLS` + `POLL_INTERVAL_SEC`：稳定检测窗口，默认 `3 * 5s`
- `CLEAR_TARGET_BEFORE_RUN`：是否清理旧训练目录，默认 `true`
- `RUN_ONCE`：一次处理后退出，默认 `true`

### 3.3 Spann3R 推理层（`demo.py`）

- `SPANN3R_KF_EVERY`：关键帧间隔，默认 `5`
  - 场景变化慢：增大到 `8~12` 降耗
  - 运动快/视角跨度大：减小到 `3~5` 提升稳定性
  - 当前转换脚本会按同一 `kf_every` 选择图片，避免 `transforms.json` 与位姿错配
- `SPANN3R_RESOLUTION`：推理分辨率，默认 `224`
  - 显存紧张时可降到 `192` 或 `160`
  - 几何细节优先时维持 `224`
- `SPANN3R_CONF_THRESH`：点云置信度阈值，默认 `0.01`
  - 噪点多：提高到 `0.02~0.05`
  - 细节缺失：降低到 `0.005~0.01`
- `SPANN3R_VOXEL_SIZE`：点云下采样粒度
  - 默认 `0.01`（约 1cm）
  - 大场景可提高到 `0.02`，小物体可降到 `0.005`
  - 系统会保留 raw/downsampled 两份点云，训练默认使用 downsampled

### 3.4 训练层（Nerfstudio）

- `VIEWER_PORT`：网页 Viewer 端口，默认 `6006`
- `TRAIN_SPLIT_FRACTION`：训练集占比，默认 `0.9`
- `NS_TRAIN_EXTRA_ARGS`：透传给 `ns-train` 的额外参数（高级调参入口）
- `NS_EXPORT_AFTER_TRAIN`：训练结束后自动导出 Gaussian 点云
- `GAUSSIAN_CROP_PADDING_RATIO`：按 Spann3R 输入点云边界裁切 Gaussian 点云时的扩展比例
- `GAUSSIAN_REF_DISTANCE_SCALE`：按参考点云邻域距离过滤漂浮噪点的倍数阈值

### 3.5 后端管理层（Dashboard）

- `DASHBOARD_AUTH_TOKEN`：可选；设置后，Dashboard 的管理类 `POST` 接口需要 `X-Auth-Token`

---

## 4. 本地运行（非 Docker）

在 `Spann3R` 目录下：

```bash
cp .env.pipeline.example .env.pipeline
set -a && source .env.pipeline && set +a
bash start_all.sh
```

检查服务：

```bash
curl http://127.0.0.1:${UPLOAD_PORT:-6008}/healthz
curl http://127.0.0.1:${UPLOAD_PORT:-6008}/stats
```

---

## 5. Docker 镜像复用方案

### 5.1 准备

```bash
cp .env.pipeline.example .env.pipeline
mkdir -p runtime_data/input_images runtime_data/gs_train runtime_data/input_archive logs
```

将 `spann3r.pth` 和 `DUSt3R_ViTLarge_BaseDecoder_512_dpt.pth` 放到 `checkpoints/`。

### 5.2 启动

```bash
docker compose -f docker-compose.pipeline.yml up -d --build
```

### 5.3 观测

```bash
docker compose -f docker-compose.pipeline.yml logs -f
```

---

## 6. 常见问题排查

- 上传正常但不触发：
  - 检查 `MIN_IMG_COUNT` 是否过大
  - 检查 `WATCH_DIR` 与 `UPLOAD_SAVE_DIR` 是否一致
- Spann3R 推理报权重缺失：
  - 检查 `SPANN3R_CKPT_PATH` 和 `checkpoints/` 挂载
- `transforms.json` 不匹配图片：
  - 当前逻辑会按 `kf_every` 对图片做与推理一致的采样，再与位姿对齐
  - 若历史数据参数不一致，会自动回退到“按时间顺序前 N 张”的兜底策略
- Viewer 无法访问：
  - 检查 `VIEWER_PORT` 映射和云防火墙

---

## 7. 推荐生产化基线

1. 开启 `UPLOAD_AUTH_TOKEN`，限制来源域名  
2. 将 `RUN_ONCE=false`，配合 `ARCHIVE_INPUT=true` 实现连续批处理  
3. 将日志目录挂载持久化（`logs/`）  
4. 使用 `NS_TRAIN_EXTRA_ARGS` 做机型差异化调参
