# Spann3R 项目总体介绍（中文）

本文档用于论文撰写与项目汇报，提供可引用的项目全景：研究背景、系统架构、工程流程、核心产出与边界。

## 1. 项目定位

本项目的方法主线是：**Spann3R + 基于 Splatfacto 的 Gaussian Splatting 训练**。

Spann3R 是一个面向稀疏到中等密度图像序列的 3D 重建系统，结合 Splatfacto 后，核心目标是：

- 从多视角图像估计相机位姿与场景几何
- 生成可用于后续 NeRF / Gaussian Splatting 训练的数据资产
- 提供可落地的端到端自动化后端（上传 -> 重建 -> 训练 -> 下载）
- 通过 Spann3R 直接产出位姿与点云先验，绕过慢速 COLMAP 流程

本仓库同时包含两层能力：

1. 研究层：Spann3R 模型、训练与评估代码
2. 工程层：生产化自动流水线与后端服务

## 2. 研究来源与论文信息

论文标题：**3D Reconstruction with Spatial Memory**（arXiv 2024）  
作者：Hengyi Wang, Lourdes Agapito

仓库中保留了原始研究代码结构（`spann3r/`, `train.py`, `eval.py` 等），并在此基础上增加了面向部署的 pipeline/service 层。

## 3. 系统架构（工程视角）

### 3.1 目录分层

- `pipeline/`：编排与转换
  - `backend_4090.py`：单卡 4090 单端口阶段式流程
  - `auto_gs.py`：自动化流程核心逻辑
  - `spann3r_to_nerfstudio.py`：`npy`/位姿转 `transforms.json`
- `services/`：HTTP 服务
  - `upload_server.py`：上传接口
  - `backend_dashboard.py`：管理台 + 状态 API + 下载 API
  - `pointcloud_download_server.py`：可选独立下载服务
- `spann3r/`：模型与训练模块
- `docs/`：中文/英文文档

### 3.2 端口与交互

- `6006`：上传与 Viewer 阶段复用
- `6008`：管理台、状态监控、点云下载

该设计满足受限端口环境下的部署需求，避免额外公网端口暴露。

## 4. 端到端数据流

## 4.1 阶段 A：上传采集

- 用户/前端调用 `POST /upload`
- 文件写入 `WATCH_DIR`
- 系统根据 `MIN_IMG_COUNT + STABLE_POLLS` 判定“上传完成”

## 4.2 阶段 B：Spann3R 重建与数据入库

- 自动快照上传图片形成场景样本
- 调用 `demo.py` 生成场景重建结果
- 以 Spann3R 输出替代传统 COLMAP 的慢速 SfM/MVS 前处理
- 同步三类点云资产：
  - `*_raw.ply`
  - `*_downsampled.ply`
  - `*_init.ply`（训练输入）
- 转换生成 Nerfstudio 所需 `transforms.json`

## 4.3 阶段 C：Gaussian 训练与可视化

- 启动 `ns-train splatfacto`
- Viewer 绑定 `6006`
- 训练完成后自动触发 Gaussian 导出（可配置）

## 4.4 阶段 D：成果下载与管理

- 管理台实时展示阶段状态、日志、关键指标
- 下载接口按 `variant` 区分 `raw/downsampled/train/gaussian`

## 5. 关键工程特性（可写入论文“系统实现”部分）

1. 路线优化：以 Spann3R 重建结果替代慢速 COLMAP 前处理，直接进入 Splatfacto 训练。
2. 单端口阶段复用：在 6006 上实现“上传与 Viewer 互斥切换”。
3. 自动入库：重建后自动组织场景目录与元数据（`transforms.json`）。
4. 训练后导出：自动执行 Gaussian 导出并产生交付点云。
5. 结果可追溯：保存测试照片、训练日志、场景目录与最新场景标记。
6. 后台可观测：通过 dashboard API 提供阶段与进度观测。

## 6. 关键配置参数

位于 `.env.pipeline.4090`：

- 触发控制：`MIN_IMG_COUNT`, `STABLE_POLLS`, `POLL_INTERVAL_SEC`
- 重建参数：`SPANN3R_KF_EVERY`, `SPANN3R_CONF_THRESH`, `SPANN3R_VOXEL_SIZE`, `SPANN3R_RESOLUTION`
- 训练参数：`TRAIN_SPLIT_FRACTION`, `NS_TRAIN_EXTRA_ARGS`
- 导出参数：`NS_EXPORT_AFTER_TRAIN`, `GAUSSIAN_CROP_PADDING_RATIO`, `GAUSSIAN_REF_DISTANCE_SCALE`

## 7. 主要输出资产

每个场景通常包含：

- `images/`（训练图像）
- `transforms.json`（相机参数与位姿）
- `*_raw.ply`
- `*_downsampled.ply`
- `*_init.ply`
- `*_gaussian_raw.ply`（若启用导出）
- `*_gaussian_clipped.ply`（若启用导出）

## 8. 论文撰写建议用语（可直接改写）

- “我们的方法采用 Spann3R + Splatfacto 的组合路线，其核心是通过 Spann3R 绕过慢速 COLMAP 前处理流程。”
- “系统在受限网络环境下采用双端口设计（6006/6008），并通过阶段切换复用 6006 端口用于上传与可视化。”
- “为保证下游 Gaussian Splatting 训练稳定性，系统在重建后统一生成 Nerfstudio 兼容的 `transforms.json` 与结构化场景目录。”

## 9. 当前边界

- 单端口复用模式下，上传与 Viewer 不并发。
- 当前默认流程主要针对单机单卡（4090）部署。
- 训练质量与速度依赖输入图像覆盖度与参数设置。

## 10. 关联文档

- 后端接口文档（中文）：`docs/backend_api_cn.md`
- 用户手册（中文）：`docs/user_guide_cn.md`
- 项目总览（英文）：`docs/project_overview_en.md`
