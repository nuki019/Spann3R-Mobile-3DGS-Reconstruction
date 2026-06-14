# AutoDL 常用运行命令

本文档用于日常演示、训练中断、重新上传和排障。命令默认在 AutoDL 实例内执行，不记录任何登录密码或 token。

## 1. 登录实例

```bash
ssh -p <SSH_PORT> root@<AUTODL_SSH_HOST>
cd /root/autodl-tmp/Spann3R
```

`<SSH_PORT>` 和 `<AUTODL_SSH_HOST>` 以 AutoDL 控制台当前显示为准。公开仓库不记录实例密码、token 或个人专属登录命令。

## 2. 查看当前状态

```bash
curl -s http://127.0.0.1:6008/healthz
curl -s http://127.0.0.1:6008/api/progress
cat /root/autodl-tmp/Spann3R/logs/pipeline_state.json
ps -ef | grep -E 'backend_4090|backend_dashboard|upload_server|ns-train' | grep -v grep
ss -lntp | grep -E ':6006|:6008|:7006' || true
```

判断方式：

- `phase=input`：正在等待上传或上传稳定。
- `phase=spann3r`：正在执行 Spann3R 重建。
- `phase=gaussian`：正在训练或 Viewer 展示；队列模式下 6008 仍可接收新上传任务。
- `phase=completed`：流程已完成，可到下载页获取结果。

## 3. 结束当前训练

优先使用管理台接口停止流水线，这会结束 `backend_4090` 以及它启动的训练子进程。

```bash
curl -X POST http://127.0.0.1:6008/api/pipeline/stop
```

停止后检查：

```bash
ps -ef | grep -E 'backend_4090|upload_server|ns-train' | grep -v grep
ss -lntp | grep -E ':6006|:7006' || true
curl -s http://127.0.0.1:6008/api/progress
```

如果 `ns-train` 仍然存在，再执行一次强制清理：

```bash
pkill -TERM -f 'ns-train|pipeline.backend_4090|services.upload_server'
sleep 3
pkill -KILL -f 'ns-train|pipeline.backend_4090|services.upload_server' || true
```

注意：强制清理会中断训练和 Viewer，但不会删除已经写入的场景、点云和日志文件。

## 4. 重启后端并回到可上传状态

用于结束旧训练后重新采集、重新上传。队列模式默认开启，上传图片会按 session 保存到 `/root/autodl-tmp/pipeline_jobs/<job_id>/images`；关闭队列时才使用旧目录 `/root/autodl-tmp/input_images`。
每次上传会同时追加 `upload_manifest.jsonl`，用于记录帧序号、session、文件大小和保存时间；训练流程状态写入 `/root/autodl-tmp/Spann3R/logs/pipeline_state.json`。

```bash
cd /root/autodl-tmp/Spann3R
bash restart_backend_stack.sh
```

默认处理方式：

- 队列任务目录：`/root/autodl-tmp/pipeline_jobs`
- 队列归档目录：`/root/autodl-tmp/pipeline_jobs_archive/restart_时间戳`
- 旧上传图片目录：`/root/autodl-tmp/input_images`
- 归档目录：`/root/autodl-tmp/input_images_archive/restart_时间戳`
- 默认保留最近 5 次重启归档

如需改成直接清空旧上传图，可在 `.env.pipeline.4090` 中设置：

```bash
RESTART_UPLOAD_CLEANUP=delete
RESTART_QUEUE_CLEANUP=delete
```

如需临时保留旧上传图和旧队列任务不处理：

```bash
RESTART_UPLOAD_CLEANUP=keep
RESTART_QUEUE_CLEANUP=keep
```

如需只调整队列归档保留次数：

```bash
RESTART_QUEUE_ARCHIVE_KEEP=3
```

重启后确认：

```bash
curl -s http://127.0.0.1:6008/healthz
curl -s http://127.0.0.1:6008/api/progress
curl -s http://127.0.0.1:6008/upload-proxy/healthz
```

如果小程序仍显示不能上传，先确认 `curl -s http://127.0.0.1:6008/upload-proxy/healthz` 中的 `allow_upload`。队列模式下即使 `phase=gaussian/export/completed`，只要 `allow_upload=true`，首页上传按钮也应放开。

查看排队任务：

```bash
curl -s http://127.0.0.1:6008/api/jobs
```

取消尚未开始的排队任务：

```bash
curl -X POST http://127.0.0.1:6008/api/jobs/<job_id>/cancel
```

## 5. 单独启动服务

通常不需要单独启动，推荐用 `restart_backend_stack.sh`。如果只想拉起某个部分，可用：

```bash
cd /root/autodl-tmp/Spann3R
bash start_backend_ui.sh
bash start_backend_4090.sh
```

含义：

- `start_backend_ui.sh`：启动 6008 管理台、状态接口、下载页和上传代理。
- `start_backend_4090.sh`：启动自动流水线，进入上传、重建、训练流程。

## 6. 查看日志

```bash
tail -n 120 logs/backend_dashboard.log
tail -n 200 logs/backend_4090.log
tail -f logs/backend_4090.log
```

常用判断：

- 上传代理异常：看 `backend_dashboard.log`。
- 训练、Spann3R、Nerfstudio 异常：看 `backend_4090.log`。
- 训练卡住：先看日志最后 50 行，再看 GPU 和进程状态。

## 7. 查看 GPU 与磁盘

```bash
nvidia-smi
df -h
du -sh /root/autodl-tmp/Spann3R /root/autodl-tmp/gs_train /root/autodl-tmp/input_images 2>/dev/null
```

如果磁盘空间不足，优先通过管理台下载需要保留的结果，再清理旧输入图片或旧实验目录。不要直接清空整个 `/root/autodl-tmp/Spann3R`。

## 8. 常用公网地址

以 AutoDL 控制台当前映射为准。AutoDL 通常只开放指定端口映射，本项目常用：

- 6006 Viewer：`https://<viewer-public-host>:8443`
- 6008 管理台/API：`https://<dashboard-public-host>:8443`

常用页面：

- 管理台：`https://<dashboard-public-host>:8443/`
- 下载页：`https://<dashboard-public-host>:8443/downloads`
- Viewer：`https://<viewer-public-host>:8443/`
