# Spann3R Backend Deployment and Training Pipeline Guide (EN)

## 1. Scope and Access Constraints

This guide is tailored to your current deployment constraints: you can only access two backend ports:

- `6006`: upload endpoint (Phase A) and Nerfstudio Viewer (Phase C), reused in sequence
- `6008`: backend management UI, status APIs, and point-cloud downloads

No additional public ports are required.

---

## 2. Optimized Directory and File Structure

The project is now organized into clear layers:

```text
Spann3R/
├─ pipeline/                            # orchestration and data conversion (primary)
│  ├─ auto_gs.py                        # automated training orchestrator
│  ├─ backend_4090.py                   # single-4090, single-port staged workflow
│  └─ spann3r_to_nerfstudio.py          # npy/poses -> transforms.json
├─ services/                            # HTTP services (primary)
│  ├─ upload_server.py                  # upload API (/upload)
│  ├─ backend_dashboard.py              # admin UI + APIs + download page
│  └─ pointcloud_download_server.py     # standalone download server (optional)
├─ spann3r/                             # core model and training stack
├─ dust3r/                              # upstream dependency code
├─ croco/                               # upstream dependency code
├─ docs/                                # technical docs
├─ start_backend_ui.sh                  # launch dashboard on 6008
├─ start_backend_4090.sh                # launch staged pipeline on 6006
├─ restart_backend_stack.sh             # restart backend stack
├─ .env.pipeline.4090(.example)         # 4090 runtime config
└─ other core entrypoints (demo.py / train.py / eval.py, etc.)
```

Note: backend orchestration and service entrypoints are centralized in `pipeline/` and `services/`.

---

## 3. Service URLs and Port Mapping (Only 6006 / 6008)

Replace `<HOST>` with your server public IP/domain.

### 3.1 Port 6008 (Management and Downloads)

- Dashboard UI:
  - `http://<HOST>:6008/`
- Download page:
  - `http://<HOST>:6008/downloads`
- Health:
  - `http://<HOST>:6008/healthz`

### 3.2 Port 6006 (Upload / Viewer Reuse)

- Upload service (Phase A):
  - `POST http://<HOST>:6006/upload`
  - `GET  http://<HOST>:6006/healthz`
  - `GET  http://<HOST>:6006/stats`
- Viewer (Phase C, after training starts):
  - `http://<HOST>:6006/`

Important: in single-port 4090 mode, upload and viewer do **not** run simultaneously on 6006.

---

## 4. Recommended Startup Procedure

Run from project root:

```bash
cd /root/autodl-tmp/Spann3R
cp .env.pipeline.4090.example .env.pipeline.4090
bash start_backend_ui.sh      # starts 6008 dashboard
bash start_backend_4090.sh    # starts 6006 staged pipeline
```

Sanity checks:

```bash
curl http://127.0.0.1:6008/healthz
curl http://127.0.0.1:6008/api/status
```

---

## 5. End-to-End Training Pipeline

### Phase A: Upload (Port 6006)

1. `services/upload_server.py` listens on `6006`.
2. Frontend uploads frames to `/upload`.
3. `pipeline/backend_4090.py` waits until:
   - image count >= `MIN_IMG_COUNT`
   - file fingerprint is stable for `STABLE_POLLS` rounds

### Phase B: Reconstruction and Dataset Prep

1. Upload service stops to free port `6006`.
2. Uploaded frames are snapshotted to `TEST_PHOTO_ROOT/<scene_name>`.
3. `demo.py` runs Spann3R reconstruction and outputs `.npy` plus dual point clouds:
   - `*_raw.ply`: confidence-filtered raw cloud
   - `*_downsampled_vs{voxel}.ply`: voxel-downsampled cloud (default training source)
4. Auto-ingest into `SCENE_DATA_ROOT/<scene_name>`:
   - `<scene>_raw.ply`
   - `<scene>_downsampled.ply`
   - `<scene>_init.ply` (same source as downsampled, used for training compatibility)
5. `pipeline/spann3r_to_nerfstudio.py` creates `transforms.json` with pose/image alignment:
   - image sampling follows `SPANN3R_KF_EVERY`
   - frame count aligns with pose count to avoid mismatch
   - `ply_file_path` points to `<scene>_init.ply` by default

### Phase C: Training and Viewer (Port 6006)

1. Conflicting training processes are terminated if needed.
2. `ns-train splatfacto` starts, viewer binds to `6006`.
3. Access viewer at `http://<HOST>:6006/`.

### Phase D: Monitoring and Download (Port 6008)

1. Monitor pipeline status and logs from `http://<HOST>:6008/`.
2. Download point clouds from `http://<HOST>:6008/downloads` with variant labels (`raw/downsampled/train`).

---

## 6. Frontend Integration APIs

## 6.1 Upload APIs (Port 6006)

### `POST /upload`

- `Content-Type: multipart/form-data`
- form fields:
  - `frame_file` (required, jpg/jpeg/png)
  - `token` (optional, when upload auth is enabled)
- optional header:
  - `X-Auth-Token` (alternative to form `token`)

Example:

```bash
curl -X POST "http://<HOST>:6006/upload" \
  -H "X-Auth-Token: <UPLOAD_AUTH_TOKEN>" \
  -F "frame_file=@/path/to/frame.jpg"
```

### `GET /healthz`

- upload service health check.

### `GET /stats`

- cumulative upload counters.

---

## 6.2 Dashboard and Status APIs (Port 6008)

### Read-only APIs (safe for frontend polling)

- `GET /api/status`
- `GET /api/progress`
- `GET /api/logs?lines=200`
- `GET /api/uploads/summary`
- `GET /api/scenes/summary`
- `GET /healthz`

### Management APIs (optional auth)

- `POST /api/pipeline/start`
- `POST /api/pipeline/stop`
- `POST /api/config`
- `POST /api/uploads/clear`
- `POST /api/pointclouds/clear`

If `DASHBOARD_AUTH_TOKEN` is configured, these `POST` APIs require:

- `X-Auth-Token: <DASHBOARD_AUTH_TOKEN>`

---

## 6.3 Download APIs (Port 6008)

- `GET /downloads`: human-friendly download page
- `GET /files`: point-cloud JSON index (includes `variant`: `gaussian/raw/downsampled/train/other`)
- `GET /download/latest?prefer=gaussian`: latest Gaussian training cloud
- `GET /download/latest?prefer=downsampled`: latest Spann3R downsampled cloud
- `GET /download/{file_id}`: file-by-id download

---

## 7. Backend UI URLs and Operations

UI entry: `http://<HOST>:6008/`

Recommended UI flow:

1. Open dashboard and confirm health is OK.
2. Fill "Management Token (optional)" if API protection is enabled.
3. Click "Start Pipeline".
4. Track:
   - uploaded image count
   - current stage (`input -> spann3r -> gaussian -> completed`)
   - real-time logs (dark terminal-like panel)
5. If you need an immediate export, click "导出最新Gaussian点云" (`POST /api/gaussian/export_latest`).
6. When training starts, open `http://<HOST>:6006/` for viewer.
7. Download the key variants from `http://<HOST>:6008/downloads`:
   - `gaussian_clipped` for delivery (exported and clipped by Spann3R bounds)
   - `raw` for before/after comparison
   - `downsampled` for delivery/training result

---

## 8. Recommended Configuration

- Upload security:
  - enable `UPLOAD_AUTH_TOKEN`
  - restrict `UPLOAD_ALLOW_ORIGINS`
- Dashboard security:
  - enable `DASHBOARD_AUTH_TOKEN`
- Trigger stability:
  - tune `MIN_IMG_COUNT`, `STABLE_POLLS`, `POLL_INTERVAL_SEC`
- Reconstruction quality:
  - tune `SPANN3R_KF_EVERY`, `SPANN3R_CONF_THRESH`, `SPANN3R_VOXEL_SIZE`
- Post-training export and clipping:
  - `NS_EXPORT_AFTER_TRAIN`
  - `GAUSSIAN_CROP_PADDING_RATIO`
  - `GAUSSIAN_REF_DISTANCE_SCALE`

---

## 9. Spann3R Downsampling Deliverable

1. `demo.py` logs raw point count, downsampled point count, and keep ratio.  
2. The system preserves both raw and downsampled point clouds and exposes both on port `6008`.  
3. Training uses the downsampled source by default (`<scene>_init.ply` mirrors `<scene>_downsampled.ply`) to balance quality and runtime.  
4. After training, the pipeline runs `ns-export gaussian-splat` and outputs:
   - `<scene>_gaussian_raw.ply`
   - `<scene>_gaussian_clipped.ply` (cropped by Spann3R downsampled bounds with `GAUSSIAN_CROP_PADDING_RATIO`)

---

## 10. Constraints and Boundaries

1. This document is fully aligned with your two-port constraint (`6006` and `6008`).
2. In staged single-port mode, upload and viewer are mutually exclusive on `6006`.
3. If you need true concurrent upload + viewer, a multi-port architecture is required (outside current constraints).
