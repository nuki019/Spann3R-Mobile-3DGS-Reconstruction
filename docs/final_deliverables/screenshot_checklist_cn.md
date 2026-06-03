# 结题报告与答辩 PPT 截图清单

以下截图用于替换 `final_report_draft_with_placeholders.docx` 和 `final_defense_ppt_draft.pptx` 中的空图位。

## 必需截图

1. 微信小程序采集页：展示拍照/选择照片、清晰度提示、上传入口。
2. 微信小程序预览页：展示上传统计、训练状态、等待队列、点云列表。
3. AutoDL 6008 管理面板：首页状态、阶段进度、上传目录摘要。
4. AutoDL 6008 点云下载页：展示 raw / downsampled / gaussian 分类、优化下载、ZIP 打包下载。
5. 处理后点云下载对比：保留原始文件大小与优化后文件大小，例如当前测试中约 482 KB 优化到约 17 KB。
6. Nerfstudio Viewer 或浏览器预览页：展示训练或已有点云/高斯结果的可视化画面。
7. AutoDL 端口与路径方案：展示 6006 用于 Viewer、6008 用于管理 UI/上传代理/下载接口。
8. 训练日志或任务状态：展示 Spann3R 重建、Splatfacto 训练、Gaussian 导出的关键阶段。

## 可选加分截图

1. `/healthz` 健康检查页面，证明后端服务在线。
2. `/api/pointclouds/summary` 或点云清单接口，证明多文件发现与下载入口可用。
3. `/upload-proxy/stats` 上传代理统计，证明小程序上传进入 AutoDL 数据盘。
4. `/root/autodl-tmp` 存储目录与缓存目录截图，证明系统盘未被大量占用。
5. Spann3R 原始点云、下采样点云、Splatfacto Gaussian 导出点云的对比图。
6. 同一张卡上不同方案的流程/耗时/结果对比表，如 Spann3R+Splatfacto 与传统 COLMAP+Splatfacto。
7. `/root/autodl-tmp/workflow_benchmarks` 同卡短基准截图，展示 Nerfacto 20 步约 16 秒、Splatfacto 隔离修复后 20 步约 230 秒、数据盘剩余空间。

## 当前可用链接

- 6008 管理面板：`https://uu342234-z010-6c5b5490.bjb2.seetacloud.com:8443/`
- 6008 健康检查：`https://uu342234-z010-6c5b5490.bjb2.seetacloud.com:8443/healthz`
- 6008 点云下载页：`https://uu342234-z010-6c5b5490.bjb2.seetacloud.com:8443/downloads`
- 6006 Viewer：`https://u342234-z010-6c5b5490.bjb2.seetacloud.com:8443/`
