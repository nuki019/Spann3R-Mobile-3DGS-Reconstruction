# 单张 4090 后端改动原理说明（6006 单端口版）

## 1. 你的目标与约束

你要求：

1. 单张 RTX 4090 上运行  
2. 单线程 CPU 约束  
3. 上传端口和 viewer 端口都使用 `6006`  
4. 给出可直接启动的后端代码

关键现实约束：同一时刻同一主机端口只能被一个进程绑定。  
因此“上传服务 + viewer 同时都占用 6006”在系统层面不可行。

---

## 2. 端口复用策略（核心原理）

采用“**分阶段端口复用**”：

1. 阶段 A：上传服务先绑定 `6006`，接收图片  
2. 阶段 B：检测上传稳定后，自动停止上传服务释放 `6006`  
3. 阶段 C：启动 `ns-train`，viewer 绑定同一个 `6006`

这样保持了你“上传和 viewer 都是 6006”的要求，同时符合 OS 端口独占规则。

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
  - 负责启动上传服务（6006）  
  - 上传稳定后自动停服  
  - 启动 Spann3R -> 转换 -> Nerfstudio（viewer 6006）

- 新增 `pipeline/auto_gs.py` 与 `pipeline/spann3r_to_nerfstudio.py`  
  - 转换阶段按 `SPANN3R_KF_EVERY` 对图片采样并与位姿对齐  
  - 减少 `transforms.json` 与推理帧错位风险

- 新增 `start_backend_4090.sh`  
  - 一条命令后台启动  
  - 统一日志输出到 `logs/backend_4090.log`

- 新增 `.env.pipeline.4090.example`  
  - 固化单卡 4090 的建议参数与单端口配置

---

## 5. 运行方式（你现在可直接用）

```bash
cd /root/autodl-tmp/Spann3R
cp .env.pipeline.4090.example .env.pipeline.4090
bash start_backend_4090.sh
```

运行后行为：

1. 先开放 `6006` 给上传接口  
2. 上传完成后自动切换到训练 viewer（仍是 `6006`）

---

## 6. 风险与边界

1. 切换瞬间（上传服务停止到 viewer 启动）`6006` 会有短暂不可用窗口。  
2. 若前端仍持续上传，会在切换后失败；建议前端有“上传结束”信号或重试逻辑。  
3. 该模式适合“先采集一批再训练”的流程，不适合同端口下实时边传边看。
4. 若通过 Dashboard 托管流水线，建议开启 `DASHBOARD_AUTH_TOKEN` 保护管理接口。
