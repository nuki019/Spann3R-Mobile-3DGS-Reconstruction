# 基于 Spann3R + Splatfacto 的移动端 3D 场景重建系统结题报告草案

本项目已完成从小程序采集、双重关键帧筛选、云端 Spann3R 重建、Splatfacto 训练、Viewer 预览到点云下载的端到端验证。结题正文建议强化算法路线、训练证据、预览可用性和下载交付，把部署细节放在答辩附录或口头说明中。

## 核心结果
- 输入：桌面视频抽帧 66 张，720x1280。
- Spann3R：11 个关键帧，11.95 FPS，原始点云 22105 点，下采样 864 点，保留率 3.91%。
- Splatfacto：60 步训练完成，Train Rays/s 约 114M-134M。
- 预览：Nerfstudio Viewer 已连接并显示场景/相机。
- 下载：Gaussian splat 约 210.8 KB，下采样点云约 23.0 KB，原始点云约 583.0 KB。

## 推荐答辩叙事
1. 手机端先通过稳定性 + 清晰度双筛，减少无效帧。
2. Spann3R 解决非标定手机图像的相机先验和初始点云问题。
3. Splatfacto 继续优化为 3D Gaussian 表达，支持实时预览与下载。
4. 同卡对比显示，本方案是本轮唯一完成采集、训练、预览、下载闭环的路线。

## 正式图表
- `charts_cn/pipeline_timeline_cn.png`
- `charts_cn/training_throughput_cn.png`
- `charts_cn/workflow_viability_cn.png`
- `charts_cn/download_artifact_sizes_cn.png`
- `charts_cn/pointcloud_reduction_cn.png`
