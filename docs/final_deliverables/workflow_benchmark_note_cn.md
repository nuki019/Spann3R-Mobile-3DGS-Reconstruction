# 同卡对比工作流部署与短基准记录

## 部署原则

对比实验全部放在 AutoDL 数据盘的隔离目录：

```text
/root/autodl-tmp/workflow_benchmarks
```

本次没有修改正在运行的 6008 后端服务，也没有在 base conda 环境中直接安装新包。额外依赖 `ninja` 安装在：

```text
/root/autodl-tmp/workflow_benchmarks/pydeps
```

Torch CUDA 扩展缓存放在：

```text
/root/autodl-tmp/workflow_benchmarks/torch_extensions
```

这样即使对比实验失败，也不会破坏原有 Spann3R + Splatfacto 主流程和后端服务。

## 远程空间与环境

- 系统盘 `/`：30GB，总体使用约 14GB，剩余约 17GB。
- 数据盘 `/root/autodl-tmp`：50GB，实验前剩余约 23GB。
- 对比实验目录最终占用约 284MB。
- GPU：NVIDIA GeForce RTX 4090，显存约 24GB。
- CUDA 工具链：`/usr/local/cuda-12.1`。
- Nerfstudio 命令：`ns-train`、`ns-process-data` 可用。
- COLMAP：不在 PATH 中，因此没有直接运行传统 COLMAP 基线，避免临时安装破坏环境。

## 样本数据

使用已有场景：

```text
/root/autodl-tmp/gs_train/scenes/scene_20260418_151918_83bf1769
```

该场景包含：

- 64 张图片；
- `transforms.json`；
- raw 点云约 11.78MB；
- downsampled/init 点云约 482KB。

另复制 24 张小样本到：

```text
/root/autodl-tmp/workflow_benchmarks/sample_images
```

用于后续 COLMAP / ns-process-data 基线尝试。

## 短基准结果

| 工作流 | 命令/方法 | 迭代数 | 结果 | 耗时 | 说明 |
| --- | --- | ---: | --- | ---: | --- |
| Nerfacto | `ns-train nerfacto` | 20 | 成功 | 16 秒 | 证明当前 Nerfstudio 训练框架可启动；日志提示缺少 `tiny-cuda-nn`，速度不是最佳。 |
| Splatfacto | `ns-train splatfacto` | 20 | 首次失败 | 12 秒 | 失败原因为 `gsplat` CUDA 扩展无法加载，缺少 `ninja`。 |
| Splatfacto 隔离修复 | `CUDA_HOME=/usr/local/cuda-12.1` + 隔离 `ninja` + `TORCH_EXTENSIONS_DIR` | 20 | 成功 | 230 秒 | 首次编译 CUDA 扩展耗时较长；后续复用扩展缓存会更快。 |
| COLMAP + Splatfacto | `ns-process-data images` + `ns-train splatfacto` | 未跑完整 | 暂缓 | - | `colmap` 不在 PATH 中，正式对比前建议单独安装到隔离 conda 环境。 |

## 对主流程优越性的说明

1. 传统 COLMAP 基线需要额外安装和维护 COLMAP，且对手机非标定输入和拍摄质量更敏感；在当前 AutoDL 实例中不应临时污染原环境。
2. Nerfacto 可作为神经渲染基线，但短迭代结果显示其训练框架能启动，不代表移动端实时展示和点云下载更优。
3. Splatfacto 是主流程的高斯训练核心，但依赖 `gsplat` CUDA 扩展；隔离修复后可运行，说明当前同卡环境具备运行 Splatfacto 的能力。
4. 本项目的优势在于用 Spann3R 先生成位姿和初始点云，再进入 Splatfacto，使非标定手机数据更容易形成可训练输入，同时保留 3DGS 的 Viewer 展示优势。
5. 下载层的裁切/下采样进一步降低点云文件体积，使输出不仅能训练，也更适合移动端下载和答辩演示。

## 后续完整对比建议

正式答辩前若时间允许，可在隔离环境中补充：

1. 安装独立 COLMAP 环境，不改 base conda；
2. 对同一组 30 到 60 张照片运行 `ns-process-data images`；
3. 分别训练 COLMAP + Splatfacto、Spann3R + Splatfacto、Nerfacto；
4. 记录预处理耗时、训练启动耗时、是否成功、显存占用、输出点云大小和 Viewer 主观效果；
5. 将结果图替换进 XeTeX 报告和 PPT 第 10 页。
