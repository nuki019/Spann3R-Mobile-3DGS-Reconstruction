# Spann3R 用户使用手册（中文）

本文档面向日常使用者，不要求阅读代码。目标是完成一次完整流程：上传图片 -> 训练 -> 查看 Viewer -> 下载点云。

## 1. 你会用到的地址

将 `<HOST>` 替换为你的服务器 IP 或域名。

- 管理台：`http://<HOST>:6008/`
- 下载页：`http://<HOST>:6008/downloads`
- Viewer：`http://<HOST>:6006/`
- 上传代理：`http://<HOST>:6008/upload-proxy/upload`

注意：

- `6008` 是日常入口，负责管理台、状态接口、上传代理和下载页。
- `6006` 主要用于 Nerfstudio Viewer，可视化通常在 Gaussian 阶段可用。

## 2. 首次启动

在服务器执行：

```bash
cd /root/autodl-tmp/Spann3R
cp .env.pipeline.4090.example .env.pipeline.4090
bash start_backend_ui.sh
bash start_backend_4090.sh
```

健康检查：

```bash
curl http://127.0.0.1:6008/healthz
curl http://127.0.0.1:6008/upload-proxy/healthz
curl http://127.0.0.1:6008/api/status
```

## 3. 重启后端（常用）

更完整的停止训练、重启、排障命令见 `backend/docs/autodl_ops_commands_cn.md`。

```bash
cd /root/autodl-tmp/Spann3R
bash restart_backend_stack.sh
```

该命令会自动停止旧进程并重新拉起 6008 + 6006。

## 4. 一次完整操作流程

### 第 1 步：打开管理台

访问 `http://<HOST>:6008/`，确认页面可打开。

### 第 2 步：上传照片

可通过你的前端页面上传，也可用接口上传：

```bash
curl -X POST "http://<HOST>:6006/upload" \
  -F "frame_file=@/path/to/frame.jpg"
```

若使用当前 6008 上传代理，推荐：

```bash
curl -X POST "http://<HOST>:6008/upload-proxy/upload" \
  -F "frame_file=@/path/to/frame.jpg"
```

建议：

- 使用同一场景、连续拍摄照片
- 图片数量至少达到 `MIN_IMG_COUNT`（默认 60）
- 上传完成后等待系统自动判定“稳定”

### 第 3 步：观察阶段切换

管理台会显示阶段：

- `input`：等待上传完成
- `spann3r`：执行重建与数据转换
- `gaussian`：执行训练与导出
- `completed`：完成

### 第 4 步：打开 Viewer

当阶段进入 `gaussian` 后，访问：

- `http://<HOST>:6006/`

### 第 5 步：下载结果

训练完成后进入：

- `http://<HOST>:6008/downloads`

常见输出：

- `*_raw.ply`：Spann3R 原始点云
- `*_downsampled.ply`：下采样点云（训练默认使用）
- `*_gaussian_clipped.ply`：训练导出并裁切后的交付点云

## 5. 常见问题

### 5.1 6006 打不开

可能原因：

- 还在上传阶段，Viewer 尚未启动
- 进程异常退出

处理：

1. 先看 `http://<HOST>:6008/` 当前阶段。
2. 重启后端：`bash restart_backend_stack.sh`。
3. 查看日志：`logs/backend_4090.log`。

### 5.2 6008 打不开

通常是 dashboard 进程未启动或端口冲突。

处理：

1. 执行 `bash restart_backend_stack.sh`。
2. 查看 `logs/backend_dashboard.log`。

### 5.3 上传后一直不开始训练

检查：

- 图片数量是否达到 `MIN_IMG_COUNT`
- 上传目录是否仍在持续变化（系统会等待稳定）
- `.env.pipeline.4090` 的 `WATCH_DIR` 是否正确

## 6. 日志位置

- `logs/backend_dashboard.log`
- `logs/backend_4090.log`

排障时优先看这两个文件。

## 7. 关键结论

- 平时只需要记住两个端口：`6006` 和 `6008`
- 最常用命令只有一个：`bash restart_backend_stack.sh`
- 以管理台 `6008` 作为总入口，观察全流程状态最稳
