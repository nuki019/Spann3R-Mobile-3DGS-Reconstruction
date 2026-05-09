# Spann3R 后端部署与训练管线总览（中文）

## 1. 适用范围与访问约束

本文档面向当前仓库的后端部署形态，假设你只能访问本机对外暴露的两个端口：

- `6006`：上传入口（阶段 A）与 Nerfstudio Viewer（阶段 C）复用
- `6008`：后端管理 UI、状态接口与点云下载

你不需要访问其他端口。

---

## 2. 目录与文件结构（优化后）

当前工程已按“编排层 / 服务层 / 模型层”做分层：

```text
Spann3R/
├─ pipeline/                            # 训练编排与数据转换（新主目录）
│  ├─ auto_gs.py                        # 自动流水线主编排
│  ├─ backend_4090.py                   # 单卡4090单端口复用流程
│  └─ spann3r_to_nerfstudio.py          # npy/pose -> transforms.json
├─ services/                            # HTTP服务（新主目录）
│  ├─ upload_server.py                  # 上传服务（/upload）
│  ├─ backend_dashboard.py              # 管理UI + API + 下载页面
│  └─ pointcloud_download_server.py     # 独立下载服务（可选）
├─ spann3r/                             # 核心模型与训练代码
├─ dust3r/                              # 上游依赖代码
├─ croco/                               # 上游依赖代码
├─ docs/                                # 中文技术文档
├─ start_backend_ui.sh                  # 启动 6008 管理UI
├─ start_backend_4090.sh                # 启动 6006 单端口流水线
├─ restart_backend_stack.sh             # 重启后端栈
├─ .env.pipeline.4090(.example)         # 4090 模式配置
└─ 其他核心入口（demo.py / train.py / eval.py 等）
```

说明：后端编排与服务入口统一收敛在 `pipeline/` 与 `services/`。

---

## 3. 服务地址与端口映射（仅 6006 / 6008）

将 `<HOST>` 替换为你的后端公网 IP 或域名。

### 3.1 6008（管理与下载）

- 管理 UI：首页
  - `http://<HOST>:6008/`
- 点云下载页
  - `http://<HOST>:6008/downloads`
- 健康检查
  - `http://<HOST>:6008/healthz`

### 3.2 6006（上传 / Viewer 复用）

- 上传服务（阶段 A）
  - `POST http://<HOST>:6006/upload`
  - `GET  http://<HOST>:6006/healthz`
  - `GET  http://<HOST>:6006/stats`
- Viewer（阶段 C，训练启动后）
  - `http://<HOST>:6006/`

注意：`6006` 在 4090 单端口模式下是**分阶段复用**，上传与 Viewer 不会并存。

---

## 4. 启动方式（推荐）

在项目根目录执行：

```bash
cd /root/autodl-tmp/Spann3R
cp .env.pipeline.4090.example .env.pipeline.4090
bash start_backend_ui.sh      # 启动 6008
bash start_backend_4090.sh    # 启动 6006（先上传，后viewer）
```

检查：

```bash
curl http://127.0.0.1:6008/healthz
curl http://127.0.0.1:6008/api/status
```

---

## 5. 全训练管线梳理（端到端）

### 阶段 A：上传阶段（6006）

1. `services/upload_server.py` 监听 `6006`。
2. 前端持续上传图片到 `/upload`。
3. `pipeline/backend_4090.py` 轮询 `WATCH_DIR`，满足：
   - 图片数 >= `MIN_IMG_COUNT`
   - 连续 `STABLE_POLLS` 轮文件指纹不变

### 阶段 B：重建与数据准备

1. 自动关闭上传服务，释放 `6006`。
2. 快照上传图片到 `TEST_PHOTO_ROOT/<scene_name>`。
3. 调用 `demo.py` 执行 Spann3R 重建，产出 `.npy` 与双点云：
   - `*_raw.ply`：置信度过滤后的原始点云
   - `*_downsampled_vs{voxel}.ply`：体素下采样点云（训练默认使用）
4. 自动入库到 `SCENE_DATA_ROOT/<scene_name>`：
   - `<scene>_raw.ply`
   - `<scene>_downsampled.ply`
   - `<scene>_init.ply`（与 downsampled 同源，供训练/兼容）
5. 调用 `pipeline/spann3r_to_nerfstudio.py` 生成 `transforms.json`：
   - 按 `SPANN3R_KF_EVERY` 做同节拍采样对齐
   - 与位姿数量对齐，避免错配
   - `ply_file_path` 默认指向 `<scene>_init.ply`

### 阶段 C：训练与可视化（6006）

1. 清理冲突训练进程（若占用同端口）。
2. 启动 `ns-train splatfacto`，Viewer 绑定 `6006`。
3. 前端/用户切换访问 `http://<HOST>:6006/` 查看训练。

### 阶段 D：下载与管理（6008）

1. 通过 `http://<HOST>:6008/downloads` 下载点云（可区分 raw/downsampled/train）。
2. 通过 `http://<HOST>:6008/` 查看阶段、日志、场景资产。

---

## 6. 前端接入接口（必须项）

## 6.1 上传接口（6006）

### `POST /upload`

- `Content-Type: multipart/form-data`
- 字段：
  - `frame_file`（必填，jpg/jpeg/png）
  - `token`（可选，启用上传鉴权时使用）
- Header（可选）：
  - `X-Auth-Token`（与 `token` 二选一）

示例：

```bash
curl -X POST "http://<HOST>:6006/upload" \
  -H "X-Auth-Token: <UPLOAD_AUTH_TOKEN>" \
  -F "frame_file=@/path/to/frame.jpg"
```

### `GET /healthz`

- 上传服务健康检查。

### `GET /stats`

- 返回累计上传文件数和字节数。

---

## 6.2 管理与状态接口（6008）

### 只读接口（前端可直接轮询）

- `GET /api/status`
- `GET /api/progress`
- `GET /api/logs?lines=200`
- `GET /api/uploads/summary`
- `GET /api/scenes/summary`
- `GET /healthz`

### 管理接口（可选鉴权）

- `POST /api/pipeline/start`
- `POST /api/pipeline/stop`
- `POST /api/config`
- `POST /api/uploads/clear`
- `POST /api/pointclouds/clear`

当配置 `DASHBOARD_AUTH_TOKEN` 后，上述 `POST` 接口需要 Header：

- `X-Auth-Token: <DASHBOARD_AUTH_TOKEN>`

---

## 6.3 下载接口（6008）

- `GET /downloads`：可视化下载页
- `GET /files`：点云 JSON 列表（含 `variant` 字段，`gaussian/raw/downsampled/train/other`）
- `GET /download/latest?prefer=gaussian`：下载最新 Gaussian 训练点云
- `GET /download/latest?prefer=downsampled`：下载最新 Spann3R 下采样点云
- `GET /download/{file_id}`：按 ID 下载

---

## 7. 后端 UI 操作地址与流程（6008）

入口：`http://<HOST>:6008/`

推荐操作顺序：

1. 打开首页，确认 `健康检查` 正常。
2. 在“管理接口 Token（可选）”输入框填写管理 token（若启用）。
3. 点“开始训练流程”。
4. 观察：
   - 上传目录照片数
   - 当前阶段（`input -> spann3r -> gaussian -> completed`）
   - 实时日志（暗色终端样式）
5. 如需立刻导出训练点云，可点“导出最新Gaussian点云”（调用 `POST /api/gaussian/export_latest`）。
6. 训练阶段跳转 `http://<HOST>:6006/` 查看 Viewer。
7. 训练后在 `http://<HOST>:6008/downloads` 下载三类重点点云：
   - `gaussian_clipped`：训练导出并按 Spann3R 输入边界裁切后的交付版本
   - `raw`：用于对比下采样前效果
   - `downsampled`：用于突出 Spann3R 下采样成果与训练输入

---

## 8. 关键配置建议

- 上传安全：
  - `UPLOAD_AUTH_TOKEN` 建议开启
  - `UPLOAD_ALLOW_ORIGINS` 建议限定来源域
- 管理安全：
  - `DASHBOARD_AUTH_TOKEN` 建议开启
- 稳定触发：
  - `MIN_IMG_COUNT`、`STABLE_POLLS`、`POLL_INTERVAL_SEC` 按场景调整
- 重建质量：
  - `SPANN3R_KF_EVERY`、`SPANN3R_CONF_THRESH`、`SPANN3R_VOXEL_SIZE`
- 训练后导出与裁切：
  - `NS_EXPORT_AFTER_TRAIN`
  - `GAUSSIAN_CROP_PADDING_RATIO`
  - `GAUSSIAN_REF_DISTANCE_SCALE`

---

## 9. Spann3R 下采样成果说明（可交付口径）

1. `demo.py` 日志会输出原始点数、下采样点数和保留率。  
2. 系统默认保留 raw 与 downsampled 两份点云，且都可在 `6008` 下载。  
3. 训练默认使用 downsampled（`<scene>_init.ply` 与 `<scene>_downsampled.ply` 同源），确保性能与质量平衡。  
4. 训练后自动执行 `ns-export gaussian-splat`，并产出：
   - `<scene>_gaussian_raw.ply`
   - `<scene>_gaussian_clipped.ply`（按 `GAUSSIAN_CROP_PADDING_RATIO` 基于 Spann3R 下采样点云裁切）

---

## 10. 约束与边界

1. 你当前仅可访问 `6006/6008`，本文已全部按这两个端口设计。
2. 在单端口复用模式下，`6006` 上传阶段与 Viewer 阶段互斥。
3. 若前端需要“边上传边查看 Viewer”，需改为多端口方案（不在当前约束内）。
