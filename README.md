# Spann3R - Mobile 3DGS Reconstruction

基于 [Spann3R](https://arxiv.org/abs/2408.16061)（空间记忆 3D 重建）的端到端移动端 3D 高斯溅射重建系统。支持手机采集 → 图片上传 → 点云重建 → 3DGS 训练 → 在线可视化完整流水线，前后端分离架构。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        微信小程序（前端）                         │
│  ┌──────────────────┐    ┌──────────────────────────────────┐   │
│  │   采集页 capture   │    │        预览页 preview            │   │
│  │  · 相机拍照       │───▶│  · 后端状态轮询                   │   │
│  │  · IMU 稳定性筛选  │    │  · 阶段进度 / 日志 / 指标         │   │
│  │  · Laplacian 清晰度│    │  · 管理动作（启停/导出）           │   │
│  │  · 有效帧上传      │    │  · 本地帧预览 / 联调地址复制       │   │
│  └──────────────────┘    └──────────────────────────────────┘   │
└────────────────────────┬────────────────────────┬───────────────┘
                   6006 (Viewer)            6008 (管理/上传/下载)
                         │                        │
┌────────────────────────▼────────────────────────▼───────────────┐
│                       后端服务                                    │
│  ┌───────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ upload_server  │  │backend_dash- │  │  pointcloud_download │  │
│  │ (内部/阶段式)   │  │  board(6008) │  │    server (可选)      │  │
│  └───────┬───────┘  └──────┬───────┘  └──────────────────────┘  │
│          │                 │                                      │
│  ┌───────▼─────────────────▼──────────────────────────────────┐  │
│  │              pipeline 自动化编排                              │  │
│  │  A: 上传代理 → B: Spann3R 重建 → C: 3DGS 训练 → D: 导出下载  │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐             │
│  │   Spann3R    │ │    DUSt3R    │ │  splatfacto  │             │
│  │  (空间记忆重建)│ │ (双视角立体)  │ │ (Gaussian训练)│             │
│  └──────────────┘ └──────────────┘ └──────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

## 目录结构

```
Spann3R-Mobile-3DGS-Reconstruction/
├── backend/                     # 后端：3D 重建核心 + API 服务
│   ├── pipeline/                #   自动化流水线编排
│   │   ├── auto_gs.py           #     自动流水线主编排
│   │   ├── backend_4090.py      #     单卡 4090 阶段式流程
│   │   └── spann3r_to_nerfstudio.py  # npy/pose → transforms.json
│   ├── services/                #   HTTP 微服务
│   │   ├── upload_server.py     #     上传服务（6006）
│   │   ├── backend_dashboard.py #     管理 UI + 状态 API + 下载（6008）
│   │   └── pointcloud_download_server.py
│   ├── spann3r/                 #   Spann3R 模型定义与训练
│   ├── dust3r/                  #   DUSt3R 双视角立体重建基座
│   ├── croco/                   #   CroCo ViT 骨干网络
│   ├── docs/                    #   后端详细文档（中/英）
│   ├── assets/                  #   示例数据与演示素材
│   ├── app.py                   #   Gradio 交互界面
│   ├── demo.py                  #   单场景推理入口
│   ├── train.py                 #   分布式训练入口
│   ├── eval.py                  #   模型评估入口
│   └── requirements.txt         #   Python 依赖
│
├── frontend/                    # 前端：微信小程序
│   ├── app.js                   #   应用入口（云开发初始化、globalData）
│   ├── app.json                 #   页面注册、超时、域名白名单
│   ├── app.wxss                 #   全局样式
│   ├── pages/
│   │   ├── capture/             #   采集页
│   │   │   ├── capture.js       #     相机 / IMU / 双筛选 / 上传
│   │   │   ├── capture.wxml     #     采集页模板
│   │   │   └── capture.wxss     #     采集页样式
│   │   └── preview/             #   预览页
│   │       ├── preview.js       #     后端状态轮询 / 管理动作 / 帧预览
│   │       ├── preview.wxml     #     预览页模板
│   │       └── preview.wxss     #     预览页样式
│   ├── utils/
│   │   └── oss_upload_utils.js  #   后端地址常量 / 上传实现 / 鉴权配置
│   └── docs/
│       └── frontend_guide_cn.md #   前端接入文档
│
├── README.md
└── LICENSE
```

## 端到端工作流

```
阶段 A: 上传采集 (6008 /upload-proxy)
  前端拍照 → IMU 稳定性筛选 → Laplacian 清晰度筛选 → POST /upload-proxy/upload
         ↓
阶段 B: Spann3R 重建
  快照图片 → demo.py 增量推理 → 点云(raw + downsampled) → transforms.json
         ↓
阶段 C: 3DGS 训练 (6006 → Viewer)
  ns-train splatfacto → Viewer 实时可视化
         ↓
阶段 D: 导出下载 (6008)
  ns-export gaussian-splat → *_gaussian_clipped.ply → /downloads
```

**端口说明：**

| 端口 | 用途 | 阶段 |
|------|------|------|
| 6006 | Nerfstudio Viewer | 阶段 C |
| 6008 | 管理 UI、状态 API、上传代理、点云下载 | 全阶段 |

## 快速开始

### 环境要求

- **后端**：Python 3.9+、CUDA 11.8+、NVIDIA GPU（推荐 RTX 4090）
- **前端**：微信开发者工具、基础库 2.2.3+

### 后端部署

```bash
cd backend

# 1. 创建 Conda 环境
conda create -n spann3r python=3.9 cmake=3.14.0
conda activate spann3r
conda install pytorch==2.3.0 torchvision==0.18.0 torchaudio==2.3.0 pytorch-cuda=11.8 -c pytorch -c nvidia
pip install -r requirements.txt
# 可选：开发/交付检查依赖
pip install -r requirements-dev.txt
pip install -U -f https://www.open3d.org/docs/latest/getting_started.html open3d

# 2. 编译 CUDA 内核（RoPE 位置编码）
cd croco/models/curope/ && python setup.py build_ext --inplace && cd ../../../

# 3. 下载模型权重
#    DUSt3R:    https://download.europe.naverlabs.com/ComputerVision/DUSt3R/DUSt3R_ViTLarge_BaseDecoder_512_dpt.pth
#    Spann3R:   https://drive.google.com/drive/folders/1bqtcVf8lK4VC8LgG-SIGRBECcrFqM7Wy
#    放入 checkpoints/ 目录

# 4. 配置环境变量
cp .env.pipeline.4090.example .env.pipeline.4090
# 编辑 .env.pipeline.4090 按需调整参数

# 5. 启动服务
bash start_backend_ui.sh      # 管理 UI (6008)
bash start_backend_4090.sh    # 上传 / 重建 / 训练 (6006)

# 健康检查
curl http://127.0.0.1:6008/healthz
curl http://127.0.0.1:6008/upload-proxy/healthz
```

### 前端配置

1. 用微信开发者工具打开 `frontend/` 目录
2. 修改 `utils/oss_upload_utils.js` 中的后端地址：

```javascript
// Viewer（对应后端 6006）
const VIEWER_BASE_URL = "https://your-viewer-host";
// 管理 / 上传代理 / 下载（对应后端 6008）
const DASHBOARD_BASE_URL = "https://your-host:6008";
```

3. 修改 `app.json` 中的域名白名单，确保包含后端地址
4. 如后端启用了鉴权，填写对应 token：

```javascript
const UPLOAD_AUTH_TOKEN = "";       // 上传鉴权 token
const DASHBOARD_AUTH_TOKEN = "";    // 管理接口鉴权 token
```

### 单场景 Demo（后端独立运行）

```bash
cd backend
python demo.py --demo_path ./assets/examples/s00567 --kf_every 10 --vis --vis_cam
```

## 前端详解

### 采集页（capture）

前端通过 **IMU + Laplacian 方差** 双重筛选保证采集质量：

**IMU 稳定性筛选：**
- 加速度计方差阈值 `0.8`，陀螺仪各轴阈值 `0.5`
- 需连续 2 次采样周期均稳定才判定为稳定
- 不稳定时禁止触发拍照

**清晰度筛选（Laplacian 方差）：**
- 阈值 `4`（低于此值判定为模糊）
- 使用 OffscreenCanvas 缩放至 128px 后计算 Laplacian 方差
- 计算超时 1.5s 自动放行，异常时兜底放行，watchdog 3s 防卡死

**文件持久化：**
- 默认使用微信临时文件路径完成清晰度筛选和上传，避免每次采集都写入相册
- 临时路径不可用时才回退 `wx.saveFile`，新一轮采集会清理上一次缓存

**上传门控：**
- 队列模式默认开启：`6008 /upload-proxy/healthz` 返回 `allow_upload: true` 时即可上传，新采集会进入 `<PIPELINE_JOB_ROOT>/<session_id>/images`
- 关闭队列模式时沿用旧门控：`phase ∈ {idle, input, stopped, unknown}` 且上传代理健康检查通过
- 上传批次按 `session_id` 隔离，单张卡仍按队列顺序执行 Spann3R 与 3DGaussian

### 预览页（preview）

**三级轮询策略：**

| 频率 | 周期 | 接口 |
|------|------|------|
| 高频 | 2.5s | `/api/status`、`/api/progress`、`/healthz`、`/upload-proxy/healthz` |
| 中频 | 5s | `/api/logs?lines=200` |
| 低频 | 10s | `/api/uploads/summary`、`/api/scenes/summary` |

**阶段状态机：**

| 阶段 | 上传 | Viewer | 下载 |
|------|------|--------|------|
| `idle` / `input` / `stopped` | 可用（健康检查通过时） | - | - |
| `spann3r` | 队列模式可继续接收新任务 | - | - |
| `gaussian` / `export` / `completed` | 队列模式可继续接收新任务 | 可用 | 可用 |

**管理动作（可选鉴权）：**
- 开始流程 → `POST /api/pipeline/start`
- 停止流程 → `POST /api/pipeline/stop`
- 导出 Gaussian → `POST /api/gaussian/export_latest`
- 取消排队任务 → `POST /api/jobs/{job_id}/cancel`

**任务队列：**
- 状态页轮询 `/api/jobs` 展示排队、运行、完成、失败任务。
- 未开始任务可在状态页直接取消；运行中任务仍使用“停止训练”。

## 后端 API 速览

### 上传代理（6008）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/upload-proxy/upload` | 上传图片（`multipart/form-data`，字段 `frame_file`） |
| `GET` | `/upload-proxy/healthz` | 上传代理健康检查 |
| `GET` | `/upload-proxy/stats` | 上传累计统计 |

### 管理服务（6008）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/healthz` | 健康检查 |
| `GET` | `/api/status` | 流水线进程状态（`running` / `pid`） |
| `GET` | `/api/progress` | 阶段、进度、loss、场景名 |
| `GET` | `/api/logs?lines=200` | 后端日志 |
| `GET` | `/api/jobs` | 队列任务列表 |
| `POST` | `/api/jobs/{job_id}/cancel` | 取消未开始的排队任务 |
| `GET` | `/api/uploads/summary` | 上传目录摘要 |
| `GET` | `/api/scenes/summary` | 场景与数据集摘要 |
| `POST` | `/api/pipeline/start` | 启动训练流水线 |
| `POST` | `/api/pipeline/stop` | 停止训练流水线 |
| `POST` | `/api/gaussian/export_latest` | 导出最新 Gaussian 点云 |
| `GET` | `/downloads` | 点云下载页 |
| `GET` | `/files` | 点云文件索引 |
| `GET` | `/download/latest?prefer=gaussian` | 下载最新点云 |
| `GET` | `/download/processed/latest?prefer=gaussian` | 下载最新优化点云 |

### 阶段字段（`/api/progress` → `phase`）

```
idle → input → spann3r → gaussian → completed
                                       ↑
                                     stopped
```

### 鉴权

| Token | 环境变量 | 作用域 |
|-------|----------|--------|
| 上传 | `UPLOAD_AUTH_TOKEN` | `POST /upload-proxy/upload`（Header `X-Auth-Token` 或表单 `token`） |
| 管理 | `DASHBOARD_AUTH_TOKEN` | 6008 所有 `POST` 接口（Header `X-Auth-Token`） |

未启用时保持空字符串即可。

## 关键配置参数

位于 `backend/.env.pipeline.4090`：

| 参数 | 说明 |
|------|------|
| `MIN_IMG_COUNT` | 触发重建的最少图片数 |
| `STABLE_POLLS` | 文件指纹连续不变的轮询次数 |
| `POLL_INTERVAL_SEC` | 轮询间隔（秒） |
| `SPANN3R_KF_EVERY` | 关键帧间隔 |
| `SPANN3R_CONF_THRESH` | 置信度过滤阈值 |
| `SPANN3R_VOXEL_SIZE` | 体素下采样尺寸 |
| `NS_MAX_NUM_ITERATIONS` | Splatfacto 训练步数，交付默认 1000 |
| `NS_STEPS_PER_SAVE` | Nerfstudio checkpoint 保存间隔 |
| `NS_QUIT_ON_TRAIN_COMPLETION` | 训练完成后自动退出 Viewer 并继续导出 |
| `NS_EXPORT_AFTER_TRAIN` | 训练后是否自动导出 |
| `GAUSSIAN_CROP_PADDING_RATIO` | Gaussian 裁切填充比例 |
| `PIPELINE_STATE_FILE` | 后端统一任务状态 JSON，供前端状态页读取 |
| `PIPELINE_QUEUE_ENABLED` | 启用单卡任务队列；上传按 session/job 隔离，训练按队列顺序执行 |
| `PIPELINE_JOB_ROOT` | 队列任务根目录，默认 `/root/autodl-tmp/pipeline_jobs` |
| `PIPELINE_JOB_ARCHIVE_ROOT` | 重启时队列任务归档目录 |
| `RESTART_UPLOAD_CLEANUP` | 重启时旧上传图片处理策略：`archive` / `delete` / `keep` |
| `RESTART_QUEUE_CLEANUP` | 重启时旧队列任务处理策略：`archive` / `delete` / `keep` |
| `RESTART_QUEUE_ARCHIVE_KEEP` | 队列任务归档最多保留次数 |

## 每场景产出资产

```
scene_name/
├── images/                        # 训练图像
├── transforms.json                # 相机参数与位姿（Nerfstudio 格式）
├── scene_name_raw.ply             # 原始点云
├── scene_name_downsampled.ply     # 体素下采样点云
├── scene_name_init.ply            # 训练输入（与 downsampled 同源）
├── scene_name_gaussian_raw.ply    # Gaussian 训练原始导出
└── scene_name_gaussian_clipped.ply # 边界裁切后交付版本
```

## 详细文档

**后端文档（`backend/docs/`）：**
- API 接口 — `backend_api_cn.md` / `backend_api_en.md`
- 用户指南 — `user_guide_cn.md` / `user_guide_en.md`
- 项目总览 — `project_overview_cn.md` / `project_overview_en.md`
- 自动流水线 — `auto_pipeline_cn.md`
- 数据预处理 — `data_preprocess.md`
- 部署原理 — `backend_4090_principles_cn.md`
- AutoDL 常用命令 — `autodl_ops_commands_cn.md`

**前端文档（`frontend/docs/`）：**
- 前端接入文档 — `frontend_guide_cn.md`

**根目录：**
- 后端管线部署指南 — `backend/BACKEND_PIPELINE_GUIDE_CN.md` / `_EN.md`
- 后续重构路线图 — `docs/refactor_roadmap_cn.md`

## 交付检查

提交或演示前建议运行：

```bash
python tools/api_contract_check.py
python tools/autodl_preflight_check.py --offline
python tools/test_pipeline_models.py
python tools/smoke_check_delivery.py
git diff --check
```

检查内容包括：

- 后端核心 Python 文件语法
- 前端小程序 JS 文件语法
- 后端关键 API 路由、前端队列入口、管理台队列入口合同检查
- AutoDL 演示前检查脚本（离线模式检查仓库文件、配置和磁盘空间）
- 队列任务模型与流水线状态文件模型测试
- README、运维文档和示例配置是否含明显敏感信息
- `.sh` 脚本 LF 换行配置
- README 是否包含当前 6008 上传代理、1000 步训练和点云下载说明

注意：模型权重、点云、训练输出、截图和报告渲染产物不应提交到 GitHub。

AutoDL 后端已启动时可运行实时检查：

```bash
python tools/autodl_preflight_check.py --base-url http://127.0.0.1:6008
```

## 致谢与引用声明

本项目基于学术界和开源社区的优秀成果进行工程化二次开发，在此向所有无私贡献的研究者和开发者致以最诚挚的感谢：

### 核心算法底座

* **[Spann3R: 3D Reconstruction with Spatial Memory](https://arxiv.org/abs/2408.16061)** - Hengyi Wang, Lourdes Agapito (arXiv 2024)
  本项目的核心空间记忆 3D 重建算法基础，解决了传统重建需要复杂全局优化的痛点
* **[DUSt3R: Geometric 3D Vision Made Easy](https://github.com/naver/dust3r)** - Shuzhe Wang et al. (CVPR 2024)
  提供双视角立体重建的基础模型与预训练权重
* **[Nerfstudio](https://github.com/nerfstudio-project/nerfstudio)**
  提供模块化的 3D 高斯溅射（Splatfacto）训练与可视化框架
* **[SplaTAM](https://github.com/spla-tam/SplaTAM)**
  为 3D 重建与高斯溅射的工程落地提供了重要参考

### 特别感谢

* **[hugoycj (Chongjie Ye)](https://github.com/hugoycj)**
  为上游 Spann3R 项目贡献了 **Gradio 交互界面框架与 checkpoint 自动下载功能（PR #14）** ，为本项目后端服务的工程化实现提供了重要基础

## 许可证

详见 [LICENSE](./LICENSE)
