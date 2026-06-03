# 单张 4090 后端改动原理说明（AutoDL 6006/6008 路径网关版）

## 1. 你的目标与约束

你要求：

1. 单张 RTX 4090 上运行
2. 单线程 CPU 约束
3. AutoDL 个人实例公网只稳定开放 `6006/6008`
4. 给出可直接启动的后端代码

关键现实约束：公网只有 `6006/6008` 可用，但上传、管理、下载、Viewer 都需要入口。
因此本版采用“路径网关”：`6008` 管理台按路径转发上传请求，`6006` 固定给 Viewer。

---

## 2. 路径网关策略（核心原理）

采用“**公网两端口 + 内部上传端口**”：

1. `6008`：管理 UI、状态 API、下载 API、`/upload-proxy` 上传代理
2. `7006`：上传服务内部端口，仅监听 `127.0.0.1`
3. `6006`：Nerfstudio Viewer 固定端口

这样不需要额外公网端口，也避免上传服务与 Viewer 抢占同一个 `6006`。

---

## 3. 为什么这套参数更适合单卡 4090

### 3.1 Spann3R 参数

- `SPANN3R_RESOLUTION=224`
  维持官方常用分辨率，保证几何质量，不牺牲细节。

- `SPANN3R_KF_EVERY=6`
  在上传序列较长时减少冗余关键帧，降低推理开销，仍保持轨迹稳定。

- `SPANN3R_CONF_THRESH=0.015`
  比默认更保守一点，降低噪点进入后续 GS 训练的概率。

- `SPANN3R_VOXEL_SIZE=0.008`
  轻度下采样（比 0.01 更细），兼顾点云细节与训练稳定性。

### 3.2 流水线触发参数

- `MIN_IMG_COUNT=60` + `STABLE_POLLS=3` + `POLL_INTERVAL_SEC=4`
  降低“过早触发训练”的风险，避免边上传边训练带来的姿态抖动。

### 3.3 单线程 CPU 参数

- `OMP_NUM_THREADS=1`
- `MKL_NUM_THREADS=1`
- `NUMEXPR_NUM_THREADS=1`

这些限制主要用于控制 CPU 线程膨胀，避免与 GPU 训练争抢资源导致调度抖动。

---

## 4. 代码级改动清单

- 新增 `pipeline/backend_4090.py`
  - 负责启动内部上传服务（默认 7006）
  - 通过 6008 `/upload-proxy` 对前端暴露上传能力
  - 启动 Spann3R -> 转换 -> Nerfstudio（viewer 6006）

- 新增 `pipeline/auto_gs.py` 与 `pipeline/spann3r_to_nerfstudio.py`
  - 转换阶段按 `SPANN3R_KF_EVERY` 对图片采样并与位姿对齐
  - 减少 `transforms.json` 与推理帧错位风险

- 新增 `start_backend_4090.sh`
  - 一条命令后台启动
  - 统一日志输出到 `logs/backend_4090.log`

- 更新 `.env.pipeline.4090.example`
  - 固化单卡 4090 的建议参数、路径网关、下载优化和历史资产清理配置

---

## 5. 运行方式（你现在可直接用）

```bash
cd /root/autodl-tmp/Spann3R
cp .env.pipeline.4090.example .env.pipeline.4090
bash start_backend_4090.sh
```

运行后行为：

1. `6008` 管理台提供 `/upload-proxy/upload` 给前端上传
2. 内部上传服务监听 `127.0.0.1:7006`
3. 上传完成后启动训练，Viewer 固定在 `6006`

---

## 6. 风险与边界

1. 只有一张 GPU 时，不建议并发启动多个 `ns-train`；系统采用队列串行执行。
2. 小程序端不能嵌入 WebView，因此 Viewer 与下载页仍采用复制链接后外部打开。
3. 下载默认会裁切/下采样，完整原始点云需显式使用 `processed=false`。
4. 若通过 Dashboard 托管流水线，建议开启 `DASHBOARD_AUTH_TOKEN` 保护管理接口。
