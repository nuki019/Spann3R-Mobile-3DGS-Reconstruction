# Spann3R User Guide (EN)

This guide is for daily users (no code reading required). It covers the full workflow: upload images -> train -> open Viewer -> download point clouds.

## 1. URLs You Will Use

Replace `<HOST>` with your server IP/domain.

- Dashboard: `http://<HOST>:6008/`
- Download page: `http://<HOST>:6008/downloads`
- Shared upload/viewer port: `http://<HOST>:6006/`

Important: port `6006` is reused by phase.

- Upload phase: `6006` receives images
- Training phase: `6006` serves Nerfstudio Viewer

## 2. First Startup

Run on server:

```bash
cd /root/autodl-tmp/Spann3R
cp .env.pipeline.4090.example .env.pipeline.4090
bash start_backend_ui.sh
bash start_backend_4090.sh
```

Health checks:

```bash
curl http://127.0.0.1:6008/healthz
curl http://127.0.0.1:6008/api/status
```

## 3. Backend Restart (Daily Operation)

```bash
cd /root/autodl-tmp/Spann3R
bash restart_backend_stack.sh
```

This command stops old processes and relaunches both 6008 and 6006 services.

## 4. End-to-End Usage Flow

### Step 1: Open Dashboard

Visit `http://<HOST>:6008/` and make sure it loads.

### Step 2: Upload Photos

You can upload through your frontend, or via API:

```bash
curl -X POST "http://<HOST>:6006/upload" \
  -F "frame_file=@/path/to/frame.jpg"
```

Recommendations:

- Keep photos from the same scene and continuous camera motion
- Reach at least `MIN_IMG_COUNT` images (default: 60)
- After upload, wait for stability detection

### Step 3: Watch Phase Transitions

Dashboard phases:

- `input`: waiting for upload stability
- `spann3r`: reconstruction and conversion
- `gaussian`: training and export
- `completed`: done

### Step 4: Open Viewer

When phase is `gaussian`, open:

- `http://<HOST>:6006/`

### Step 5: Download Outputs

After training, visit:

- `http://<HOST>:6008/downloads`

Common artifacts:

- `*_raw.ply`: raw Spann3R cloud
- `*_downsampled.ply`: downsampled cloud (default training source)
- `*_gaussian_clipped.ply`: exported + cropped delivery cloud

## 5. Common Issues

### 5.1 Port 6006 Is Not Reachable

Possible causes:

- Still in upload phase (viewer not started yet)
- Process exited unexpectedly

Actions:

1. Check current phase at `http://<HOST>:6008/`.
2. Restart backend: `bash restart_backend_stack.sh`.
3. Check logs: `logs/backend_4090.log`.

### 5.2 Port 6008 Is Not Reachable

Usually dashboard process not running or port conflict.

Actions:

1. Run `bash restart_backend_stack.sh`.
2. Check `logs/backend_dashboard.log`.

### 5.3 Upload Finishes but Training Does Not Start

Check:

- image count reached `MIN_IMG_COUNT`
- upload directory is stable (no ongoing file changes)
- `WATCH_DIR` in `.env.pipeline.4090` is correct

## 6. Log Files

- `logs/backend_dashboard.log`
- `logs/backend_4090.log`

Use these two first for troubleshooting.

## 7. Key Takeaways

- Only remember two ports: `6006` and `6008`
- One main ops command: `bash restart_backend_stack.sh`
- Use dashboard `6008` as the single control entrypoint
