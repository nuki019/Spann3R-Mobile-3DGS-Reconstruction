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
    run_command,
    run_conversion,
    run_pipeline_once,
    run_spann3r,
    snapshot_uploaded_images,
    terminate_conflicting_ns_train,
    wait_until_queued_job_stable,
    wait_until_upload_stable,
)
from pipeline.job_queue import mark_job, sanitize_job_id
from pipeline.task_state import PipelineStateStore


def apply_default_env() -> None:
    defaults: Dict[str, str] = {
        "WATCH_DIR": "/root/autodl-tmp/input_images",
        "TARGET_DATA_DIR": "/root/autodl-tmp/gs_train/auto_scene",
        "SCENE_DATA_ROOT": "/root/autodl-tmp/gs_train/scenes",
        "TEST_PHOTO_ROOT": "/root/autodl-tmp/Spann3R/test_photo_sets",
        "ARCHIVE_DIR": "/root/autodl-tmp/input_images_archive",
        "SCENE_NAME_PREFIX": "scene",
        "UPLOAD_SAVE_DIR": "/root/autodl-tmp/input_images",
        "PIPELINE_JOB_ROOT": "/root/autodl-tmp/pipeline_jobs",
        "UPLOAD_PORT": "6006",
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
        "NS_MAX_NUM_ITERATIONS": "1000",
        "NS_STEPS_PER_SAVE": "1000",
        "NS_QUIT_ON_TRAIN_COMPLETION": "true",
        "NS_TRAIN_EXTRA_ARGS": "",
        "NS_OUTPUT_ROOT": "/root/autodl-tmp/Spann3R/outputs",
        "NS_EXPORT_AFTER_TRAIN": "true",
        "GAUSSIAN_EXPORT_SUBDIR": "gaussian_export",
        "GAUSSIAN_CROP_PADDING_RATIO": "0.03",
        "GAUSSIAN_REF_DISTANCE_SCALE": "4.0",
        "NS_EXPORT_EXTRA_ARGS": "",
        "RUN_ONCE": "false",
        "PIPELINE_QUEUE_ENABLED": "true",
        "CLEAR_TARGET_BEFORE_RUN": "true",
        "CLEAR_INPUT_AFTER_SNAPSHOT": "true",
        "ARCHIVE_INPUT": "false",
        "MAX_SCENES_KEEP": "5",
        "MAX_PHOTO_SETS_KEEP": "5",
        "RESTART_UPLOAD_CLEANUP": "archive",
        "RESTART_UPLOAD_ARCHIVE_KEEP": "5",
        "PIPELINE_STATE_FILE": "/root/autodl-tmp/Spann3R/logs/pipeline_state.json",
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
        "0.0.0.0",
        "--port",
        str(port),
    ]
    print(f"🌐 启动上传服务: 0.0.0.0:{port}")
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
    state_store = PipelineStateStore()
    config.viewer_port = 6006
    upload_port = 6006
    if config.queue_enabled:
        print(f"📌 队列模式：6008 上传代理写入 {config.pipeline_job_root}，6006 固定留给 Viewer。")
        while True:
            try:
                run_pipeline_once(config, state_store=state_store)
                if config.run_once:
                    break
            except Exception as error:
                failed_state = state_store.fail(error)
                paths = failed_state.get("paths") if isinstance(failed_state.get("paths"), dict) else {}
                queue_job_id = str(paths.get("queue_job_id") or "")
                if queue_job_id:
                    mark_job(
                        config.pipeline_job_root,
                        queue_job_id,
                        "failed",
                        "训练失败",
                        error=str(error),
                    )
                print(f"\n❌ 队列任务异常: {error}")
                if config.run_once:
                    raise
                print(f"⏱ {config.retry_interval_sec} 秒后继续监听下一个任务...")
                time.sleep(config.retry_interval_sec)
        return

    job_seed = f"{config.scene_name_prefix}_{time.strftime('%Y%m%d_%H%M%S')}"
    state_store.start_job(
        job_seed,
        phase="input",
        message="等待上传稳定",
        paths={
            "watch_dir": str(config.watch_dir),
            "scene_data_root": str(config.scene_data_root),
            "test_photo_root": str(config.test_photo_root),
            "archive_dir": str(config.archive_dir),
        },
        metrics={
            "min_img_count": config.min_img_count,
            "stable_polls": config.stable_polls,
            "max_iterations": config.ns_max_num_iterations,
        },
    )

    try:
        print("🧭 阶段切换: 输入监测")
        queue_job = None
        if config.queue_enabled:
            print(f"📌 队列模式：6008 上传代理写入 {config.pipeline_job_root}，6006 固定留给 Viewer。")
            images_source = wait_until_queued_job_stable(config, state_store=state_store)
            queue_job, images = images_source
        else:
            print("📌 4090 单端口后端模式：上传与 Viewer 都使用 6006（分阶段复用）")
            stale_pids = terminate_conflicting_ns_train(upload_port)
            if stale_pids:
                print(f"🧹 上传阶段前已停止占用端口 {upload_port} 的旧训练进程: {stale_pids}")
            if not wait_for_port_state(upload_port, should_listen=False, timeout_sec=10.0):
                raise RuntimeError(f"端口 {upload_port} 仍被占用，无法启动上传服务。")
            upload_server = start_upload_server(upload_port, config.spann3r_root)
            try:
                images = wait_until_upload_stable(config, state_store=state_store)
            finally:
                stop_process(upload_server, "上传服务")
            if not wait_for_port_state(upload_port, should_listen=False, timeout_sec=10.0):
                raise RuntimeError(f"上传服务退出后端口 {upload_port} 仍被占用。")

        scene_name = build_scene_name(config, images)
        if queue_job:
            queued_scene = str(queue_job.get("scene_name") or "").strip()
            if queued_scene:
                scene_name = sanitize_job_id(queued_scene)
        state_store.update(
            job_id=scene_name,
            scene_name=scene_name,
            phase="input",
            status="running",
            message="上传稳定，已创建场景",
            metrics={"uploaded_images": len(images)},
            paths={
                "job_input_dir": str(images[0].parent) if images else "",
                "pipeline_job_root": str(config.pipeline_job_root),
            },
        )
        scene_photo_dir = snapshot_uploaded_images(config, images, scene_name)
        state_store.update(paths={"scene_photo_dir": str(scene_photo_dir)})

        print("🧭 阶段切换: Spann3R 重建")
        state_store.update(
            phase="spann3r",
            status="running",
            message="Spann3R 正在生成几何与相机位姿",
        )
        scene_output_dir = run_spann3r(config, scene_photo_dir, scene_name)

        scene_target_dir = config.scene_data_root / scene_name
        state_store.update(
            paths={
                "scene_output_dir": str(scene_output_dir),
                "scene_data_dir": str(scene_target_dir),
            },
        )
        prepare_target_dataset(config, source_images_dir=scene_photo_dir, target_data_dir=scene_target_dir)
        raw_name, downsampled_name, pointcloud_name = copy_point_clouds(scene_output_dir, scene_target_dir, scene_name)
        state_store.update(
            artifacts={
                "spann3r_raw": str(scene_target_dir / raw_name),
                "spann3r_downsampled": str(scene_target_dir / downsampled_name),
                "train_pointcloud": str(scene_target_dir / pointcloud_name),
            },
        )
        run_conversion(
            config,
            scene_output_dir,
            image_dir=scene_target_dir / "images",
            output_json=scene_target_dir / "transforms.json",
            ply_file_name=pointcloud_name,
            npy_name=scene_name,
        )
        mark_latest_scene(config.scene_data_root, scene_name)
        archive_summary = archive_input_images(config)
        state_store.update(paths={"upload_cleanup": archive_summary})

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
        state_store.update(
            phase="gaussian",
            status="running",
            message="3DGaussian 正在训练",
            metrics={
                "step": 0,
                "loss": "",
                "percent": 0,
                "max_iterations": config.ns_max_num_iterations,
            },
            paths={"scene_data_dir": str(scene_target_dir)},
        )
        train_start_timestamp = time.time()
        run_command(build_ns_train_command(config, scene_target_dir))
        state_store.update(
            phase="export",
            status="running",
            message="训练完成，正在导出 Gaussian 点云",
            metrics={"step": config.ns_max_num_iterations, "percent": 100},
        )
        gaussian_artifacts = export_gaussian_artifacts(config, scene_name, scene_target_dir, train_start_timestamp)
        state_store.update(
            phase="completed",
            status="completed",
            message="训练与导出完成",
            metrics={"step": config.ns_max_num_iterations, "percent": 100},
            artifacts=gaussian_artifacts,
        )
        if queue_job:
            mark_job(
                config.pipeline_job_root,
                str(queue_job.get("id") or queue_job.get("job_id") or scene_name),
                "completed",
                "训练与导出完成",
                scene_name=scene_name,
                extra={"artifacts": gaussian_artifacts, "scene_data_dir": str(scene_target_dir)},
            )
    except Exception as error:
        if "queue_job" in locals() and queue_job:
            mark_job(
                config.pipeline_job_root,
                str(queue_job.get("id") or queue_job.get("job_id") or "unknown"),
                "failed",
                "训练失败",
                error=str(error),
            )
        state_store.fail(error)
        raise


if __name__ == "__main__":
    main()
