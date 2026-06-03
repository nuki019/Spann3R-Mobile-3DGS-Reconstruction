# 后端可视化 UI 使用说明（2026-04-18）

## 1. 功能概览

当前 `services/backend_dashboard.py` 提供：

- 训练流程控制（启动/停止）
- 上传照片实时监控（数量、最近文件）
- 训练进度监控（阶段、step、loss、日志）
- 三阶段进度切换（输入监测 -> Spann3R 重建 -> Gaussian 训练/导出）
- 参数调节（附中文解释）
- 场景资产监控（场景数据集、测试照片集、点云数量）
- 一键清空：上传照片 / 历史点云
- 点云下载页与 JSON 列表，支持优化下载、原始下载和 ZIP 打包
- `/upload-proxy` 上传代理，将 6008 路径转发到内部上传服务
- 流水线等待队列，避免单卡并发训练导致显存冲突
- 暗色主题终端日志面板（适配深色终端习惯）
- 日志窗口已放大并支持 `tab-size` 显示

## 2. 启动方式

```bash
cd /root/autodl-tmp/Spann3R
cp .env.pipeline.4090.example .env.pipeline.4090
bash start_backend_ui.sh
```

- Dashboard 端口：`6008`
- 上传代理：`6008 /upload-proxy/upload`
- Viewer 端口：`6006`
- 内部上传端口：默认 `127.0.0.1:7006`

## 3. 关键页面与接口

### 3.1 页面

- `/`：后端管理台
- `/downloads`：点云下载页

### 3.2 监控接口

- `/api/status`
- `/api/progress`
- `/api/logs?lines=200`
- `/api/uploads/summary`
- `/api/scenes/summary`

### 3.3 管理接口

- `POST /api/pipeline/start`
- `POST /api/pipeline/stop`
- `POST /api/config`
- `POST /api/uploads/clear`
- `POST /api/pointclouds/clear`
- `POST /api/gaussian/export_latest`

> 若配置了 `DASHBOARD_AUTH_TOKEN`，以上管理接口需要 `X-Auth-Token`。  
> UI 页面已提供“管理接口 Token（可选）”输入框，保存在浏览器本地存储。

### 3.4 下载与健康检查

- `/files`
- `/download/latest`
- `/download/processed/latest`
- `/download/zip`
- `/download/{file_id}`
- `/healthz`
- `/upload-proxy/healthz`

说明：

- `/files` 返回点云 `variant` 字段（`gaussian/raw/downsampled/train/other`）。
- `/download/processed/latest?prefer=gaussian` 下载裁切/下采样后的最新 Gaussian 点云。
- `/download/latest?prefer=gaussian&processed=false` 下载原始 Gaussian 点云。
- `/download/zip?variant=gaussian` 打包下载 Gaussian 点云。

## 4. 多场景相关目录

新增目录约定：

- 场景训练数据：`SCENE_DATA_ROOT`（默认 `/root/autodl-tmp/gs_train/scenes`）
- 测试照片留存：`TEST_PHOTO_ROOT`（默认 `/root/autodl-tmp/Spann3R/test_photo_sets`）
- 场景命名前缀：`SCENE_NAME_PREFIX`

每次有效上传触发后，会自动生成新场景目录，便于后续多场景管理改造。

## 5. 注意事项

- `start_all.sh` 与 `start_backend_ui.sh` 都可占用 `6008`，请避免同时占用同端口。
- 清空点云操作不可恢复，建议先在 `/downloads` 备份需要的文件。
- 若启用管理接口鉴权，请同步配置调用端（例如前端或脚本）的 `X-Auth-Token`。
- AutoDL 系统盘空间有限，场景数据、上传目录、点云处理缓存建议放在 `/root/autodl-tmp`，并保留 `MAX_SCENES_KEEP`、`MAX_PHOTO_SETS_KEEP` 等清理策略。
