# Spann3R Project Overview (EN)

This document is for paper writing and project reporting. It summarizes research background, architecture, engineering pipeline, outputs, and current boundaries.

## 1. Project Positioning

The core method in this project is: **Spann3R + Splatfacto-based Gaussian Splatting training**.

Spann3R is a 3D reconstruction system for sparse-to-medium multi-view image sequences. In this combined pipeline, main goals are:

- estimate camera poses and scene geometry from images
- produce assets consumable by downstream NeRF / Gaussian Splatting pipelines
- provide a deployable backend workflow (upload -> reconstruct -> train -> download)
- bypass slow COLMAP preprocessing by using Spann3R outputs (poses and point-cloud priors) directly

This repository contains two layers:

1. Research layer: Spann3R model, training, and evaluation code
2. Engineering layer: production-style pipeline orchestration and backend services

## 2. Research Origin

Paper: **3D Reconstruction with Spatial Memory** (arXiv 2024)  
Authors: Hengyi Wang, Lourdes Agapito

The repository keeps original research modules (`spann3r/`, `train.py`, `eval.py`) and adds deployment-oriented `pipeline/` and `services/` layers.

## 3. System Architecture (Engineering View)

### 3.1 Layered Structure

- `pipeline/`: orchestration and conversion
  - `backend_4090.py`: staged single-port flow for RTX 4090
  - `auto_gs.py`: core automated pipeline logic
  - `spann3r_to_nerfstudio.py`: converts `npy` poses to `transforms.json`
- `services/`: HTTP services
  - `upload_server.py`: upload APIs
  - `backend_dashboard.py`: dashboard UI + status APIs + download APIs
  - `pointcloud_download_server.py`: optional standalone download service
- `spann3r/`: model and training modules
- `docs/`: bilingual project documents

### 3.2 Port Design

- `6006`: reused by upload phase and Viewer phase
- `6008`: dashboard, monitoring, and downloads

This supports constrained network deployments with minimal public ports.

## 4. End-to-End Data Flow

## 4.1 Phase A: Upload Ingestion

- frontend/user calls `POST /upload`
- files are saved to `WATCH_DIR`
- completion is detected by `MIN_IMG_COUNT + STABLE_POLLS`

## 4.2 Phase B: Spann3R Reconstruction and Dataset Build

- uploaded images are snapshotted as a scene package
- `demo.py` runs reconstruction
- Spann3R outputs replace the slow COLMAP SfM/MVS preprocessing stage
- three point-cloud artifacts are materialized:
  - `*_raw.ply`
  - `*_downsampled.ply`
  - `*_init.ply` (training input)
- `transforms.json` is generated for Nerfstudio compatibility

## 4.3 Phase C: Gaussian Training and Visualization

- `ns-train splatfacto` is launched
- Viewer binds to port `6006`
- post-training Gaussian export can run automatically

## 4.4 Phase D: Monitoring and Delivery

- dashboard shows phase state, logs, and key metrics
- download APIs expose variants: `raw/downsampled/train/gaussian`

## 5. Key Engineering Features (Useful in “System Implementation” Section)

1. Pipeline acceleration: Spann3R replaces slow COLMAP preprocessing so training can start earlier.
2. Single-port phase reuse: mutual switch between upload and Viewer on 6006.
3. Automatic dataset assembly: consistent scene directory + `transforms.json`.
4. Post-training export: automatic Gaussian export with deliverable artifacts.
5. Traceability: retained photo snapshots, logs, scene records, latest-scene marker.
6. Observability: dashboard APIs for pipeline state and progress.

## 6. Important Runtime Config

Defined in `.env.pipeline.4090`:

- trigger control: `MIN_IMG_COUNT`, `STABLE_POLLS`, `POLL_INTERVAL_SEC`
- reconstruction: `SPANN3R_KF_EVERY`, `SPANN3R_CONF_THRESH`, `SPANN3R_VOXEL_SIZE`, `SPANN3R_RESOLUTION`
- training: `TRAIN_SPLIT_FRACTION`, `NS_TRAIN_EXTRA_ARGS`
- export: `NS_EXPORT_AFTER_TRAIN`, `GAUSSIAN_CROP_PADDING_RATIO`, `GAUSSIAN_REF_DISTANCE_SCALE`

## 7. Main Output Artifacts

A scene typically includes:

- `images/` (training images)
- `transforms.json` (camera intrinsics/extrinsics)
- `*_raw.ply`
- `*_downsampled.ply`
- `*_init.ply`
- `*_gaussian_raw.ply` (if export enabled)
- `*_gaussian_clipped.ply` (if export enabled)

## 8. Suggested Paper Wording (Editable)

- “Our method combines Spann3R with Splatfacto-based Gaussian Splatting training, and its core value is bypassing the slow COLMAP preprocessing stage.”
- “Under constrained networking, the system uses a two-port design (6006/6008) and stage-based port reuse to support both upload and visualization.”
- “To stabilize downstream Gaussian Splatting training, reconstruction outputs are normalized into Nerfstudio-compatible scene directories with generated `transforms.json`.”

## 9. Current Boundaries

- In single-port mode, upload and Viewer are not concurrent.
- Default deployment target is single-machine single-GPU (RTX 4090).
- Quality/runtime depend on image coverage and runtime parameter settings.

## 10. Related Docs

- Backend API (CN): `docs/backend_api_cn.md`
- User Guide (EN): `docs/user_guide_en.md`
- Project Overview (CN): `docs/project_overview_cn.md`
