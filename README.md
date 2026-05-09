# Spann3R - Mobile 3DGS Reconstruction

基于 [Spann3R](https://arxiv.org/abs/2408.16061)（空间记忆 3D 重建）的端到端移动端 3D 高斯溅射重建系统。支持图片上传 → 点云重建 → 3DGS 训练 → 在线可视化完整流水线，前后端分离架构。

## 目录结构

```
Spann3R-Mobile-3DGS-Reconstruction/
├── backend/                # 后端：3D 重建核心 + API 服务
│   ├── spann3r/            #   Spann3R 模型定义与训练
│   ├── dust3r/             #   DUSt3R 双视角立体重建基座
│   ├── croco/              #   CroCo ViT 骨干网络
│   ├── pipeline/           #   自动化流水线编排
│   ├── services/           #   HTTP 微服务（上传/管理/下载）
│   ├── docs/               #   后端详细文档（中/英）
│   ├── assets/             #   示例数据与演示素材
│   ├── app.py              #   Gradio 交互界面
│   ├── demo.py             #   单场景推理入口
│   ├── eval.py             #   模型评估入口
│   ├── train.py            #   分布式训练入口
│   └── requirements.txt    #   Python 依赖
├── frontend/               # 前端：（待开发）
├── README.md
└── LICENSE
```

## 快速开始

### 环境要求

- Python 3.9+
- CUDA 11.8+
- NVIDIA GPU（推荐 RTX 4090）

### 后端部署

```bash
cd backend

# 1. 创建 Conda 环境
conda create -n spann3r python=3.9 cmake=3.14.0
conda activate spann3r
conda install pytorch==2.3.0 torchvision==0.18.0 torchaudio==2.3.0 pytorch-cuda=11.8 -c pytorch -c nvidia
pip install -r requirements.txt
pip install -U -f https://www.open3d.org/docs/latest/getting_started.html open3d

# 2. 编译 CUDA 内核（RoPE 位置编码）
cd croco/models/curope/ && python setup.py build_ext --inplace && cd ../../../

# 3. 下载模型权重
#    DUSt3R: https://download.europe.naverlabs.com/ComputerVision/DUSt3R/DUSt3R_ViTLarge_BaseDecoder_512_dpt.pth
#    Spann3R v1.01: https://drive.google.com/drive/folders/1bqtcVf8lK4VC8LgG-SIGRBECcrFqM7Wy
#    放入 checkpoints/ 目录

# 4. 配置环境变量
cp .env.pipeline.4090.example .env.pipeline.4090

# 5. 启动服务
bash start_backend_ui.sh      # 管理 UI (6008)
bash start_backend_4090.sh    # 上传/重建 (6006)
```

### 单场景 Demo

```bash
cd backend
python demo.py --demo_path ./assets/examples/s00567 --kf_every 10 --vis --vis_cam
```

## 后端架构

```
图片上传 (6006)
    ↓
Spann3R 点云重建（空间记忆增量推理）
    ↓
Nerfstudio 格式转换
    ↓
3D Gaussian Splatting 训练（splatfacto）
    ↓
在线 Viewer 可视化 (6006) + 点云下载 (6008)
```

**端口说明：**

| 端口 | 用途 |
|------|------|
| 6006 | 上传服务（阶段 A）→ Nerfstudio Viewer（阶段 C）自动切换 |
| 6008 | 管理 UI、任务状态 API、点云文件下载 |

## 后端文档

后端详细文档位于 `backend/docs/`：

- **API 接口** — `backend_api_cn.md` / `backend_api_en.md`
- **用户指南** — `user_guide_cn.md` / `user_guide_en.md`
- **项目总览** — `project_overview_cn.md` / `project_overview_en.md`
- **自动流水线** — `auto_pipeline_cn.md`
- **4090 部署原理** — `backend_4090_principles_cn.md`
- **数据预处理** — `data_preprocess.md`

## 前端（规划中）

前端模块待开发，计划支持：

- 移动端图片上传界面
- 重建进度实时追踪
- 3DGS 在线查看器

## 致谢

本项目基于以下优秀开源工作：

- [Spann3R](https://github.com/HengyiWang/spann3r) — Hengyi Wang, Lourdes Agapito (arXiv 2024)
- [DUSt3R](https://github.com/naver/dust3r)
- [Nerfstudio](https://github.com/nerfstudio-project/nerfstudio)
- [SplaTAM](https://github.com/spla-tam/SplaTAM)

## 许可证

详见 [LICENSE](./LICENSE)
