# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Spann3R 是一个基于空间记忆（Spatial Memory）的 3D 重建系统，输入为多视角图片序列，输出稠密点云与相机位姿。系统构建了一条端到端的自动化流水线：图片上传 → Spann3R 重建 → Nerfstudio/Splatfacto 高斯溅射训练 → 可视化与导出。

## 常用命令

### 环境搭建

```bash
conda create -n spann3r python=3.9 cmake=3.14.0
conda install pytorch==2.3.0 torchvision==0.18.0 torchaudio==2.3.0 pytorch-cuda=11.8 -c pytorch -c nvidia
pip install -r requirements.txt
pip install -U -f https://www.open3d.org/docs/latest/getting_started.html open3d  # Open3D 需用 dev 版

# 编译 CUDA 内核（RoPE 位置编码）
cd croco/models/curope/ && python setup.py build_ext --inplace && cd ../../../
```

### 运行 Demo

```bash
python demo.py --demo_path ./examples/s00567 --kf_every 10 --vis --vis_cam
# 动态场景模式
python demo.py --demo_path ./examples/s00567 --kf_every 10 --vis --vis_cam --dynamic
# 保存原始相机参数（供 Nerfstudio 使用）
python demo.py --demo_path ./examples/s00567 --kf_every 10 --vis --vis_cam --save_ori
```

### 训练与评估

```bash
torchrun --nproc_per_node 8 train.py --batch_size 4    # 多卡训练
python eval.py                                          # 评估
```

### Gradio 界面

```bash
python app.py                    # 默认端口 7860
python app.py --server_port 8080 --share
```

### 后端流水线（4090 单卡模式）

```bash
cp .env.pipeline.4090.example .env.pipeline.4090   # 首次部署必须
bash start_backend_ui.sh      # 启动 6008 管理 UI + 下载
bash start_backend_4090.sh    # 启动 6006 上传/Viewer 复用端口
bash restart_backend_stack.sh # 重启全部后端服务

# 健康检查
curl http://127.0.0.1:6008/healthz
curl http://127.0.0.1:6008/api/status
```

## 架构分层

```
Spann3R/
├── spann3r/          # 模型层：核心模型定义、数据集、训练逻辑
│   ├── model.py      # Spann3R 模型（含 SpatialMemory 类）
│   ├── loss.py       # Scale-Shift-Invariant 回归损失
│   ├── training.py   # 训练循环（torchrun 分布式）
│   ├── datasets/     # 多数据集适配器（ScanNet/Co3D/DTU 等）
│   └── tools/        # 评估与可视化工具
├── dust3r/           # 上游依赖：DUSt3R（双视角立体 3D 重建）
│   ├── model.py      # AsymmetricCroCo3DStereo 基类
│   ├── inference.py  # 推理逻辑（make_pairs → inference）
│   └── heads/        # 回归头（深度/点云/置信度预测）
├── croco/            # 上游依赖：CroCo ViT 骨干网络
│   └── models/       # Block、RoPE 位置编码（含 CUDA 内核）
├── pipeline/         # 编排层：自动化训练管线
│   ├── auto_gs.py    # 主编排器（PipelineConfig + 端到端流程）
│   ├── backend_4090.py   # 单卡 4090 单端口复用编排
│   └── spann3r_to_nerfstudio.py  # 点云/位姿 → transforms.json 转换
├── services/         # 服务层：HTTP 微服务
│   ├── upload_server.py          # FastAPI 上传服务（6006）
│   ├── backend_dashboard.py      # FastAPI 管理 UI + API（6008）
│   └── pointcloud_download_server.py  # 点云下载服务
├── demo.py           # 单场景推理入口（核心调用链）
├── app.py            # Gradio 交互界面
├── train.py          # 分布式训练入口
└── eval.py           # 评估入口（DTU/7Scenes/NRGBD/Replica）
```

## 核心调用链

**推理重建路径**（demo.py）:
1. `Spann3R` 模型加载 → 包含 `SpatialMemory`（工作记忆 + 长期记忆）
2. `Spann3R.forward()` 逐帧处理 → 维护空间记忆的键值缓存（mem_k/mem_v/mem_c）
3. `DUSt3R` 回归头预测每帧 3D 点云 + 置信度
4. 置信度过滤 → 体素下采样 → 输出 `raw.ply` 与 `downsampled.ply`

**自动化流水线路径**（pipeline/backend_4090.py）:
1. **阶段 A**: `upload_server` 监听上传，`backend_4090` 轮询 `WATCH_DIR` 直到图片数量达标且稳定
2. **阶段 B**: 关闭上传服务 → 快照图片 → 调用 `demo.py` 重建 → 转换 Nerfstudio 格式
3. **阶段 C**: 启动 `ns-train splatfacto` → 6006 切换为 Viewer
4. **阶段 D**: 训练完成后自动导出 Gaussian 点云并裁切，6008 提供下载

## 端口规划

| 端口 | 用途 | 服务入口 |
|------|------|---------|
| 6006 | 上传服务（阶段A）→ Nerfstudio Viewer（阶段C）复用 | `services/upload_server.py` / splatfacto |
| 6008 | 管理 UI、状态 API、点云下载 | `services/backend_dashboard.py` |

6006 在单端口模式下上传与 Viewer 互斥，由 `backend_4090.py` 自动切换。

## 关键配置

所有流水线配置通过 `.env.pipeline` 或 `.env.pipeline.4090` 环境变量文件注入，核心参数：

- `SPANN3R_KF_EVERY`：关键帧间隔，影响重建质量与速度
- `SPANN3R_CONF_THRESH`：置信度阈值，过滤低质量 3D 点
- `SPANN3R_VOXEL_SIZE`：体素下采样尺寸，影响点云密度
- `MIN_IMG_COUNT` / `STABLE_POLLS`：自动触发重建的最小图片数与稳定轮数
- `GAUSSIAN_CROP_PADDING_RATIO`：Gaussian 导出时的裁切边距

## 模型依赖关系

`spann3r.model.Spann3R` 继承自 `dust3r.model.AsymmetricCroCo3DStereo`，后者使用 `croco.models.blocks.Block`（CroCo ViT）。`Spann3R` 的核心创新是 `SpatialMemory` 类，通过维护工作记忆（最近 N 帧）和长期记忆（高注意力键值对）实现增量式 3D 重建。CUDA 编译产物 `curope` 通过符号链接指向 `submodules/dust3r/croco/models/curope/`。

## 文档索引

详细文档位于 `docs/` 目录：
- `backend_api_cn.md` / `backend_api_en.md` — 后端 API 接口文档
- `user_guide_cn.md` / `user_guide_en.md` — 用户操作指南
- `project_overview_cn.md` / `project_overview_en.md` — 项目总览
- `auto_pipeline_cn.md` — 自动管线流程说明
- `backend_4090_principles_cn.md` — 单卡 4090 部署原理
- `data_preprocess.md` — 训练数据集预处理指南
