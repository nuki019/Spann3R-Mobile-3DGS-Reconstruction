import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Dict

from pipeline.auto_gs import (
    PipelineConfig,
    archive_input_images,
    build_scene_name,
    build_ns_train_command,
    copy_point_clouds,
    export_gaussian_artifacts,
    mark_latest_scene,
    prepare_target_dataset,
    prune_old_assets,
    run_command,
    run_conversion,
    run_spann3r,
    snapshot_uploaded_images,
    terminate_conflicting_ns_train,
    wait_until_upload_stable,
)


def apply_default_env() -> None:
    defaults: Dict[str, str] = {
        "WATCH_DIR": "/root/autodl-tmp/input_images",
        "TARGET_DATA_DIR": "/root/autodl-tmp/gs_train/auto_scene",
        "SCENE_DATA_ROOT": "/root/autodl-tmp/gs_train/scenes",
        "TEST_PHOTO_ROOT": "/root/autodl-tmp/Spann3R/test_photo_sets",
        "SCENE_NAME_PREFIX": "scene",
        "UPLOAD_SAVE_DIR": "/root/autodl-tmp/input_images",
        "UPLOAD_INTERNAL_PORT": "7006",
        "UPLOAD_PORT": "7006",
        "VIEWER_PORT": "6006",
        "SPANN3R_DEVICE": "cuda:0",
        "SPANN3R_RESOLUTION": "224",
        "SPANN3R_KF_EVERY": "6",
        "SPANN3R_CONF_THRESH": "0.015",
        "SPANN3R_VOXEL_SIZE": "0.008",
        "MIN_IMG_COUNT": "60",
        "STABLE_POLLS": "3",
        "POLL_INTERVAL_SEC": "4",
        "TRAIN_SPLIT_FRACTION": "0.95",
        "NS_OUTPUT_ROOT": "/root/autodl-tmp/Spann3R/outputs",
        "NS_EXPORT_AFTER_TRAIN": "true",
        "GAUSSIAN_EXPORT_SUBDIR": "gaussian_export",
        "GAUSSIAN_CROP_PADDING_RATIO": "0.03",
        "GAUSSIAN_REF_DISTANCE_SCALE": "4.0",
        "NS_EXPORT_EXTRA_ARGS": "",
        "RUN_ONCE": "true",
        "CLEAR_TARGET_BEFORE_RUN": "true",
        "ARCHIVE_INPUT": "false",
        "CLEAR_INPUT_AFTER_SNAPSHOT": "true",
        "MAX_SCENES_KEEP": "5",
        "MAX_PHOTO_SETS_KEEP": "5",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def load_env_file() -> None:
    script_dir = Path(__file__).resolve().parent.parent
    env_path = script_dir / ".env.pipeline.4090"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def is_port_listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def wait_for_port_state(port: int, should_listen: bool, timeout_sec: float = 10.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if is_port_listening(port) == should_listen:
            return True
        time.sleep(0.25)
    return is_port_listening(port) == should_listen


def start_upload_server(port: int, cwd: Path) -> subprocess.Popen:
    command = [
        "python",
        "-m",
        "uvicorn",
        "services.upload_server:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    print(f"🌐 启动内部上传服务: 127.0.0.1:{port}")
    process = subprocess.Popen(command, cwd=str(cwd))
    time.sleep(1.0)
    if process.poll() is not None:
        raise RuntimeError(
            f"上传服务启动失败，端口 {port} 被占用或进程异常退出。请先清理旧进程后重试。"
        )
    if not wait_for_port_state(port, should_listen=True, timeout_sec=8.0):
        stop_process(process, "上传服务")
        raise RuntimeError(f"上传服务未成功监听端口 {port}。")
    return process


def stop_process(process: subprocess.Popen, name: str) -> None:
    if process.poll() is not None:
        return
    print(f"🛑 停止{name}，释放端口...")
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> None:
    load_env_file()
    apply_default_env()

    config = PipelineConfig.from_env()
    config.viewer_port = 6006
    upload_port = int(os.getenv("UPLOAD_INTERNAL_PORT", os.getenv("UPLOAD_PORT", "7006")))

    print("📌 4090 路径网关模式：6008 /upload-proxy -> 内部上传端口，6006 固定留给 Viewer")
    if not wait_for_port_state(upload_port, should_listen=False, timeout_sec=10.0):
        raise RuntimeError(f"端口 {upload_port} 仍被占用，无法启动上传服务。")
    upload_server = start_upload_server(upload_port, config.spann3r_root)

    try:
        print("🧭 阶段切换: 输入监测")
        images = wait_until_upload_stable(config)
    finally:
        stop_process(upload_server, "上传服务")
    if not wait_for_port_state(upload_port, should_listen=False, timeout_sec=10.0):
        raise RuntimeError(f"上传服务退出后端口 {upload_port} 仍被占用。")

    scene_name = build_scene_name(config, images)
    scene_photo_dir = snapshot_uploaded_images(config, images, scene_name)
    print("🧭 阶段切换: Spann3R 重建")
    scene_output_dir = run_spann3r(config, scene_photo_dir, scene_name)

    scene_target_dir = config.scene_data_root / scene_name
    prepare_target_dataset(config, source_images_dir=scene_photo_dir, target_data_dir=scene_target_dir)
    _, _, pointcloud_name = copy_point_clouds(scene_output_dir, scene_target_dir, scene_name)
    run_conversion(
        config,
        scene_output_dir,
        image_dir=scene_target_dir / "images",
        output_json=scene_target_dir / "transforms.json",
        ply_file_name=pointcloud_name,
        npy_name=scene_name,
    )
    mark_latest_scene(config.scene_data_root, scene_name)
    prune_old_assets(config, scene_name)
    archive_input_images(config)

    print(f"✅ 场景入库完成: {scene_target_dir}")
    stale_pids = terminate_conflicting_ns_train(config.viewer_port, keep_data_dir=scene_target_dir)
    if stale_pids:
        print(f"🧹 训练阶段前已停止端口 {config.viewer_port} 的冲突训练进程: {stale_pids}")
    if not wait_for_port_state(config.viewer_port, should_listen=False, timeout_sec=10.0):
        raise RuntimeError(
            f"端口 {config.viewer_port} 仍被其他服务占用，无法保证 Viewer 固定在该端口。"
        )
    print("🧭 阶段切换: Gaussian 训练/导出")
    print("🔥 上传阶段完成，切换到训练 Viewer（6006）...")
    train_start_timestamp = time.time()
    run_command(build_ns_train_command(config, scene_target_dir))
    export_gaussian_artifacts(config, scene_name, scene_target_dir, train_start_timestamp)


if __name__ == "__main__":
    main()
