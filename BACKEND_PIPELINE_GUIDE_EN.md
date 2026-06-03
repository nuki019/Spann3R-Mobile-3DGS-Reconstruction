# Spann3R + Splatfacto Backend Pipeline Guide (AutoDL 6006/6008)

This guide covers the current backend workflow: mobile upload -> Spann3R reconstruction -> Splatfacto training -> point-cloud delivery.

## 1. Port Plan

- `6006`: Nerfstudio Viewer.
- `6008`: dashboard, status APIs, download APIs, and `/upload-proxy`.
- `7006`: internal upload service, bound to `127.0.0.1` and proxied by `6008 /upload-proxy`.

This fits the common AutoDL personal-instance constraint where `6006/6008` are the usable public service ports.

## 2. Startup

```bash
cd /root/autodl-tmp/Spann3R
cp .env.pipeline.4090.example .env.pipeline.4090
bash restart_backend_stack.sh
```

Health checks:

```bash
curl http://127.0.0.1:6008/healthz
curl http://127.0.0.1:6008/upload-proxy/healthz
curl http://127.0.0.1:6008/api/status
```

## 3. Workflow

1. Open `http://<HOST>:6008/` for the dashboard.
2. Upload through `http://<HOST>:6008/upload-proxy/upload`.
3. When image count reaches `MIN_IMG_COUNT` and remains stable, the pipeline runs Spann3R reconstruction.
4. During Gaussian training, open `http://<HOST>:6006/` for Viewer.
5. After training/export, download point clouds from `http://<HOST>:6008/downloads`.

## 4. Key Optimizations

- Uploads are written as `.part` files and atomically replaced to prevent partial-file reads.
- `_upload_manifest.jsonl` records batch ID, frame index, sharpness, IMU stability, and sha256.
- Point-cloud downloads default to `processed=true`, applying spatial cropping and voxel downsampling; original files are available with `processed=false`.
- `/download/zip` supports multi-file downloads.
- Repeated start requests are queued and executed serially instead of launching concurrent GPU-heavy training jobs.
- Uploads, scenes, and processed point-cloud caches default to `/root/autodl-tmp`, with cleanup controlled by `MAX_SCENES_KEEP`, `MAX_PHOTO_SETS_KEEP`, and `PROCESSED_DOWNLOAD_MAX_FILES`.

## 5. Common APIs

- `GET /api/status`: running state, active job, and queue.
- `GET /api/progress`: phase, step, loss, and export summaries.
- `POST /api/pipeline/start`: start or enqueue a training job.
- `POST /api/pipeline/stop`: stop current job and clear queued jobs.
- `GET /api/pointclouds/summary`: point-cloud summary.
- `GET /download/processed/latest?prefer=gaussian`: optimized latest Gaussian point cloud.
- `GET /download/latest?prefer=gaussian&processed=false`: original latest Gaussian point cloud.

## 6. Notes

- Personal WeChat mini-programs cannot use WebView, so Viewer and download pages are exposed as copyable external links.
- On one GPU, running multiple `ns-train` jobs concurrently is unstable; the queue demonstrates multi-task handling while keeping execution serial.
- `/root/autodl-tmp` is suitable for large files and caches, but important results should still be downloaded or backed up.
