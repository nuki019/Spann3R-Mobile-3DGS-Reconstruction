# 结题交付说明

## 本次优化范围

本次围绕上传、训练、下载三个层面完成端到端可用性优化。

- 上传层：小程序通过 6008 的 `/upload-proxy` 进入 AutoDL 内部上传服务，避免个人小程序无法使用 WebView 的限制；上传前保留本地预览、进度统计、失败重试与状态提示。
- 训练层：6008 管理面板提供训练启动、停止、状态轮询、日志摘要、阶段进度和等待队列；单卡环境默认串行执行训练任务，避免多个 `ns-train` 同时抢占显存。
- 下载层：点云下载默认走处理后文件，支持空间裁切、体素下采样、缓存复用、按场景/类型筛选与 ZIP 打包；原始点云仍可通过 `processed=false` 下载。
- 文件管理：上传照片、场景数据、处理后点云缓存均放在 `/root/autodl-tmp` 数据盘；缓存有最大数量和保留时长限制，避免系统盘堆积。
- 前后端 UI：小程序预览页增加后端健康、训练队列、上传摘要、场景摘要和点云清单；6008 管理 UI 增加配置、进度、点云下载和清理入口。

## 已验证结果

- 远程 6008 `/healthz` 返回 200，后端状态正常。
- 远程 6008 `/api/status` 返回运行状态、PID 与队列长度。
- 远程 6008 `/api/pointclouds/summary` 可发现 10 个历史点云文件。
- 远程处理后单文件下载成功，示例下采样点云由约 482 KB 生成约 17 KB 处理后 `.ply`。
- 远程处理后 ZIP 下载成功，示例 ZIP 包含 4 个处理后点云文件。
- 本地 Python 语法检查通过：`services/upload_server.py`、`services/pointcloud_download_server.py`、`services/backend_dashboard.py`、`pipeline/auto_gs.py`、`pipeline/backend_4090.py`。
- 结题报告 DOCX 与答辩 PPTX 均通过压缩包结构检查，PPTX 包含 12 页。

## 报告与 PPT 文件

- 结题报告 XeTeX 源文件：`docs/final_deliverables/final_report_xetex.tex`
- 结题报告 PDF：`docs/final_deliverables/final_report_xetex.pdf`
- 备用 Word 草稿：`docs/final_deliverables/final_report_draft_with_placeholders.docx`
- 答辩 PPT 草稿：`docs/final_deliverables/final_defense_ppt_draft.pptx`
- 截图清单：`docs/final_deliverables/screenshot_checklist_cn.md`
- 同卡对比工作流记录：`docs/final_deliverables/workflow_benchmark_note_cn.md`

XeTeX 版报告在本机已使用以下命令编译通过：

```bash
xelatex -interaction=nonstopmode -halt-on-error final_report_xetex.tex
xelatex -interaction=nonstopmode -halt-on-error final_report_xetex.tex
```

## 使用说明

1. 小程序端不要改成 WebView 内嵌，继续采用复制链接、跳转浏览器或电脑端打开的方案。
2. 微信公众平台后台还需要手动加入 6006/6008 对应域名到 request/download/upload 合法域名。
3. 真实训练前先确认 `/root/autodl-tmp/input_images` 为空或只包含本次上传照片。
4. 若需要展示多方案优越性，建议在同一张卡上补充一组小规模对照：传统 COLMAP+Splatfacto、Spann3R-only 点云、Spann3R+Splatfacto，并记录耗时、成功率、点云大小和视觉效果。

## 同卡短基准补充

已在 AutoDL 数据盘隔离目录 `/root/autodl-tmp/workflow_benchmarks` 完成短基准，不修改当前后端环境：

- Nerfacto 20 步：成功，约 16 秒。
- Splatfacto 20 步：首次因 `gsplat` CUDA 扩展缺少 `ninja` 失败；将 `ninja`、Torch 扩展缓存隔离到数据盘后成功，首次编译约 230 秒。
- COLMAP + Splatfacto：因 `colmap` 不在 PATH 中暂缓，建议后续建独立 conda 环境再跑完整基线。
