# Spann3R + Splatfacto 后端流水线指南（AutoDL 6006/6008 版）

本文用于部署与演示当前后端流水线：移动端上传图片 -> Spann3R 重建 -> Splatfacto 训练 -> 点云下载。

## 1. 端口规划

- `6006`：Nerfstudio Viewer。
- `6008`：管理台、状态接口、下载接口、`/upload-proxy` 上传代理。
- `7006`：上传服务内部端口，仅监听 `127.0.0.1`，由 `6008 /upload-proxy` 转发。

该方案适配 AutoDL 个人实例常用的 `6006/6008` 公网映射限制，不额外暴露端口。

## 2. 启动

```bash
cd /root/autodl-tmp/Spann3R
cp .env.pipeline.4090.example .env.pipeline.4090
bash restart_backend_stack.sh
```

健康检查：

```bash
curl http://127.0.0.1:6008/healthz
curl http://127.0.0.1:6008/upload-proxy/healthz
curl http://127.0.0.1:6008/api/status
```

## 3. 使用流程

1. 打开 `http://<HOST>:6008/` 查看管理台。
2. 前端或脚本上传到 `http://<HOST>:6008/upload-proxy/upload`。
3. 管理台等待图片数达到 `MIN_IMG_COUNT` 且连续稳定后，自动进入 Spann3R 重建。
4. 进入 Gaussian 阶段后，打开 `http://<HOST>:6006/` 查看 Viewer。
5. 训练或导出完成后，在 `http://<HOST>:6008/downloads` 下载点云。

## 4. 关键优化

- 上传文件先写 `.part`，再原子替换为正式图片，避免流水线读到半截文件。
- 上传清单 `_upload_manifest.jsonl` 记录批次、帧号、清晰度、IMU 稳定性与 sha256。
- 点云下载默认 `processed=true`，会按参考点云进行空间裁切和体素下采样；原始文件使用 `processed=false`。
- 支持 `/download/zip` 多文件打包下载。
- 多次点击启动不会并发训练，而是进入等待队列，在单张 GPU 上串行执行。
- 上传目录、场景目录、处理后点云缓存默认放在 `/root/autodl-tmp`，并由 `MAX_SCENES_KEEP`、`MAX_PHOTO_SETS_KEEP`、`PROCESSED_DOWNLOAD_MAX_FILES` 控制清理。

## 5. 常用接口

- `GET /api/status`：流水线运行状态、当前任务、等待队列。
- `GET /api/progress`：阶段、step、loss、点云导出摘要。
- `POST /api/pipeline/start`：启动或排队一个训练任务。
- `POST /api/pipeline/stop`：停止当前任务并清空等待队列。
- `GET /api/pointclouds/summary`：点云列表摘要。
- `GET /download/processed/latest?prefer=gaussian`：优化后最新 Gaussian 点云。
- `GET /download/latest?prefer=gaussian&processed=false`：原始最新 Gaussian 点云。

## 6. 注意事项

- 小程序个人注册端不能使用 WebView，因此 Viewer 和下载页采用复制链接后外部浏览器打开。
- 单卡不建议并发运行多个 `ns-train`；当前队列设计用于展示多任务能力，同时保证稳定。
- AutoDL 的 `/root/autodl-tmp` 适合放大文件和缓存，但仍建议把重要实验结果及时下载或同步到仓库/网盘。
