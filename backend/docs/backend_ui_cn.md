# 后端可视化 UI 使用说明（2026-04-18）

## 1. 功能概览

当前 `services/backend_dashboard.py` 提供：

- 训练流程控制（启动/停止）
- 上传照片实时监控（数量、最近文件）
- 任务队列监控（排队、运行、完成、失败统计）
- 取消尚未开始的排队任务
- 训练进度监控（阶段、step、loss、日志）
- 三阶段进度切换（输入监测 -> Spann3R 重建 -> Gaussian 训练/导出）
- 参数调节（附中文解释）
- 场景资产监控（场景数据集、测试照片集、点云数量）
- 一键清空：上传照片 / 历史点云
- 点云下载页与 JSON 列表
- 暗色主题终端日志面板（适配深色终端习惯）
- 日志窗口已放大并支持 `tab-size` 显示

## 2. 启动方式

```bash
cd /root/autodl-tmp/Spann3R
cp .env.pipeline.4090.example .env.pipeline.4090
bash start_backend_ui.sh
```

- Dashboard 端口：`6008`
- 上传代理、管理台和下载页：`6008`
- Viewer 端口：`6006`

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
- `/api/jobs`

### 3.3 管理接口

- `POST /api/pipeline/start`
- `POST /api/pipeline/stop`
- `POST /api/config`
- `POST /api/uploads/clear`
- `POST /api/jobs/{job_id}/cancel`
- `POST /api/pointclouds/clear`
- `POST /api/gaussian/export_latest`

> 若配置了 `DASHBOARD_AUTH_TOKEN`，以上管理接口需要 `X-Auth-Token`。  
> UI 页面已提供“管理接口 Token（可选）”输入框，保存在浏览器本地存储。

### 3.4 下载与健康检查

- `/files`
- `/download/latest`
- `/download/{file_id}`
- `/healthz`

说明：

- `/files` 返回点云 `variant` 字段（`gaussian/raw/downsampled/train/other`）。
- `/download/latest?prefer=gaussian` 直接下载训练导出的 Gaussian 点云。
- `/download/latest?prefer=downsampled` 下载 Spann3R 下采样输入点云用于对比。

## 4. 多场景相关目录

新增目录约定：

- 场景训练数据：`SCENE_DATA_ROOT`（默认 `/root/autodl-tmp/gs_train/scenes`）
- 队列任务输入：`PIPELINE_JOB_ROOT`（默认 `/root/autodl-tmp/pipeline_jobs`）
- 队列任务归档：`PIPELINE_JOB_ARCHIVE_ROOT`（默认 `/root/autodl-tmp/pipeline_jobs_archive`）
- 测试照片留存：`TEST_PHOTO_ROOT`（默认 `/root/autodl-tmp/Spann3R/test_photo_sets`）
- 场景命名前缀：`SCENE_NAME_PREFIX`

每次有效上传会按 session 生成队列任务，训练流程按单卡顺序消费，并为每个任务生成独立场景目录。

## 5. 注意事项

- `start_all.sh` 与 `start_backend_ui.sh` 都可占用 `6008`，请避免同时占用同端口。
- 清空点云操作不可恢复，建议先在 `/downloads` 备份需要的文件。
- 若启用管理接口鉴权，请同步配置调用端（例如前端或脚本）的 `X-Auth-Token`。
