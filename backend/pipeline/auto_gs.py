import os
import hashlib
import shlex
import shutil
import subprocess
import signal
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import open3d as o3d

from pipeline.job_queue import (
    build_image_fingerprint as build_job_image_fingerprint,
    job_images_dir,
    list_images as list_job_images,
    list_runnable_jobs,
    mark_job,
    sanitize_job_id,
)
from pipeline.task_state import PipelineStateStore

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"}


def _get_env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class PipelineConfig:
    watch_dir: Path
    spann3r_root: Path
    demo_output_root: Path
    target_data_dir: Path
    scene_data_root: Path
    test_photo_root: Path
    archive_dir: Path
    pipeline_job_root: Path
    scene_name_prefix: str
    viewer_port: int
    min_img_count: int
    stable_polls: int
    poll_interval_sec: float
    retry_interval_sec: float
    train_split_fraction: float
    conf_thresh: float
    kf_every: int
    resolution: int
    voxel_size: float
    device: str
    ckpt_path: str
    save_ori: bool
    run_once: bool
    clear_target_before_run: bool
    archive_input: bool
    queue_enabled: bool
    clear_input_after_snapshot: bool
    max_scene_keep: int
    max_photo_sets_keep: int
    ns_max_num_iterations: int
    ns_steps_per_save: int
    ns_quit_on_train_completion: bool
    ns_train_extra_args: str
    ns_output_root: Path
    ns_export_after_train: bool
    gaussian_export_subdir: str
    gaussian_crop_padding_ratio: float
    gaussian_ref_distance_scale: float
    ns_export_extra_args: str

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        root = Path(os.getenv("SPANN3R_ROOT", Path(__file__).resolve().parent.parent))
        legacy_target_data_dir = Path(os.getenv("TARGET_DATA_DIR", "/root/autodl-tmp/gs_train/auto_scene"))
        scene_data_root = Path(os.getenv("SCENE_DATA_ROOT", str(legacy_target_data_dir.parent / "scenes")))
        return cls(
            watch_dir=Path(os.getenv("WATCH_DIR", "/root/autodl-tmp/input_images")),
            spann3r_root=root,
            demo_output_root=Path(os.getenv("DEMO_OUTPUT_ROOT", str(root / "output" / "demo"))),
            target_data_dir=legacy_target_data_dir,
            scene_data_root=scene_data_root,
            test_photo_root=Path(os.getenv("TEST_PHOTO_ROOT", str(root / "test_photo_sets"))),
            archive_dir=Path(os.getenv("ARCHIVE_DIR", "/root/autodl-tmp/input_images_archive")),
            pipeline_job_root=Path(os.getenv("PIPELINE_JOB_ROOT", "/root/autodl-tmp/pipeline_jobs")),
            scene_name_prefix=os.getenv("SCENE_NAME_PREFIX", "scene"),
            viewer_port=int(os.getenv("VIEWER_PORT", "6006")),
            min_img_count=int(os.getenv("MIN_IMG_COUNT", "50")),
            stable_polls=int(os.getenv("STABLE_POLLS", "3")),
            poll_interval_sec=float(os.getenv("POLL_INTERVAL_SEC", "5")),
            retry_interval_sec=float(os.getenv("RETRY_INTERVAL_SEC", "15")),
            train_split_fraction=float(os.getenv("TRAIN_SPLIT_FRACTION", "0.9")),
            conf_thresh=float(os.getenv("SPANN3R_CONF_THRESH", "0.01")),
            kf_every=int(os.getenv("SPANN3R_KF_EVERY", "5")),
            resolution=int(os.getenv("SPANN3R_RESOLUTION", "224")),
            voxel_size=float(os.getenv("SPANN3R_VOXEL_SIZE", "0.01")),
            device=os.getenv("SPANN3R_DEVICE", "cuda:0"),
            ckpt_path=os.getenv("SPANN3R_CKPT_PATH", "./checkpoints/spann3r.pth"),
            save_ori=_get_env_bool("SPANN3R_SAVE_ORI", False),
            run_once=_get_env_bool("RUN_ONCE", True),
            clear_target_before_run=_get_env_bool("CLEAR_TARGET_BEFORE_RUN", True),
            archive_input=_get_env_bool("ARCHIVE_INPUT", False),
            queue_enabled=_get_env_bool("PIPELINE_QUEUE_ENABLED", True),
            clear_input_after_snapshot=_get_env_bool("CLEAR_INPUT_AFTER_SNAPSHOT", True),
            max_scene_keep=int(os.getenv("MAX_SCENES_KEEP", "5")),
            max_photo_sets_keep=int(os.getenv("MAX_PHOTO_SETS_KEEP", "5")),
            ns_max_num_iterations=int(os.getenv("NS_MAX_NUM_ITERATIONS", "1000")),
            ns_steps_per_save=int(os.getenv("NS_STEPS_PER_SAVE", "1000")),
            ns_quit_on_train_completion=_get_env_bool("NS_QUIT_ON_TRAIN_COMPLETION", True),
            ns_train_extra_args=os.getenv("NS_TRAIN_EXTRA_ARGS", "").strip(),
            ns_output_root=Path(os.getenv("NS_OUTPUT_ROOT", str(root / "outputs"))),
            ns_export_after_train=_get_env_bool("NS_EXPORT_AFTER_TRAIN", True),
            gaussian_export_subdir=os.getenv("GAUSSIAN_EXPORT_SUBDIR", "gaussian_export").strip() or "gaussian_export",
            gaussian_crop_padding_ratio=float(os.getenv("GAUSSIAN_CROP_PADDING_RATIO", "0.03")),
            gaussian_ref_distance_scale=float(os.getenv("GAUSSIAN_REF_DISTANCE_SCALE", "4.0")),
            ns_export_extra_args=os.getenv("NS_EXPORT_EXTRA_ARGS", "").strip(),
        )


def run_command(command: Sequence[str], cwd: Optional[Path] = None) -> None:
    print(f"\n>> 执行命令: {shlex.join(command)}")
    subprocess.run(command, cwd=str(cwd) if cwd else None, check=True)


def list_images(directory: Path) -> List[Path]:
    images = [p for p in directory.iterdir() if p.is_file() and p.suffix in IMAGE_EXTENSIONS]
    images.sort(key=lambda p: (p.stat().st_mtime_ns, p.name))
    return images


def build_image_fingerprint(images: Iterable[Path]) -> Tuple[Tuple[str, int, int], ...]:
    return tuple((path.name, path.stat().st_size, path.stat().st_mtime_ns) for path in images)


def sanitize_name(raw: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in raw.strip())
    cleaned = cleaned.strip("_")
    return cleaned or "scene"


def build_scene_name(config: PipelineConfig, images: Iterable[Path]) -> str:
    prefix = sanitize_name(config.scene_name_prefix)
    fingerprint = build_image_fingerprint(images)
    digest = hashlib.sha1(repr(fingerprint).encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{digest}"


def snapshot_uploaded_images(config: PipelineConfig, images: List[Path], scene_name: str) -> Path:
    scene_photo_dir = config.test_photo_root / scene_name
    if scene_photo_dir.exists():
        shutil.rmtree(scene_photo_dir)
    scene_photo_dir.mkdir(parents=True, exist_ok=True)
    for image_path in images:
        shutil.copy2(image_path, scene_photo_dir / image_path.name)
    print(f"🗂️ 已保留测试照片集: {scene_photo_dir} (共 {len(images)} 张)")
    return scene_photo_dir


def wait_until_upload_stable(
    config: PipelineConfig,
    state_store: Optional[PipelineStateStore] = None,
) -> List[Path]:
    config.watch_dir.mkdir(parents=True, exist_ok=True)
    print(f"🚀 流水线已启动，监听目录: {config.watch_dir}")
    print(
        f"📌 触发条件: 至少 {config.min_img_count} 张，且连续 {config.stable_polls} 轮文件指纹不变"
    )

    stable_rounds = 0
    last_fingerprint: Tuple[Tuple[str, int, int], ...] = tuple()
    while True:
        images = list_images(config.watch_dir)
        image_count = len(images)
        if image_count >= config.min_img_count:
            fingerprint = build_image_fingerprint(images)
            if fingerprint == last_fingerprint:
                stable_rounds += 1
                print(
                    f"⌛ 上传稳定检测中: {stable_rounds}/{config.stable_polls} | 图片数: {image_count}",
                    end="\r",
                )
            else:
                stable_rounds = 0
                print(f"📈 已检测到图片: {image_count}，继续等待上传完成...", end="\r")
            last_fingerprint = fingerprint
            if state_store:
                state_store.update(
                    phase="input",
                    status="running",
                    message="正在检测上传是否稳定",
                    metrics={
                        "uploaded_images": image_count,
                        "stable_rounds": stable_rounds,
                        "stable_polls": config.stable_polls,
                        "min_img_count": config.min_img_count,
                    },
                    paths={"watch_dir": str(config.watch_dir)},
                )
            if stable_rounds >= config.stable_polls:
                print(f"\n✅ 上传完成确认，共 {image_count} 张图片。")
                if state_store:
                    state_store.update(
                        phase="input",
                        status="running",
                        message="上传已稳定，准备创建场景",
                        metrics={
                            "uploaded_images": image_count,
                            "stable_rounds": stable_rounds,
                            "stable_polls": config.stable_polls,
                            "min_img_count": config.min_img_count,
                        },
                    )
                return images
        else:
            print(
                f"🕒 当前图片 {image_count} 张，未达到阈值 {config.min_img_count} 张，持续监听...",
                end="\r",
            )
            if state_store:
                state_store.update(
                    phase="input",
                    status="running",
                    message="等待上传达到最小图片数",
                    metrics={
                        "uploaded_images": image_count,
                        "stable_rounds": stable_rounds,
                        "stable_polls": config.stable_polls,
                        "min_img_count": config.min_img_count,
                    },
                    paths={"watch_dir": str(config.watch_dir)},
                )
        time.sleep(config.poll_interval_sec)


def wait_until_queued_job_stable(
    config: PipelineConfig,
    state_store: Optional[PipelineStateStore] = None,
) -> Tuple[Dict[str, object], List[Path]]:
    config.pipeline_job_root.mkdir(parents=True, exist_ok=True)
    stable_state: Dict[str, Tuple[Tuple[Tuple[str, int, int], ...], int]] = {}
    print(f"🧾 队列模式已启用，监听任务目录: {config.pipeline_job_root}")

    while True:
        jobs = list_runnable_jobs(config.pipeline_job_root)
        queue_length = len(jobs)
        if not jobs:
            if state_store:
                state_store.update(
                    phase="input",
                    status="running",
                    message="等待新的上传任务进入队列",
                    metrics={
                        "queue_length": 0,
                        "uploaded_images": 0,
                        "min_img_count": config.min_img_count,
                        "stable_polls": config.stable_polls,
                    },
                    paths={"pipeline_job_root": str(config.pipeline_job_root)},
                )
            time.sleep(config.poll_interval_sec)
            continue

        for job in jobs:
            job_id = sanitize_job_id(str(job.get("id") or job.get("job_id") or ""))
            images_dir = job_images_dir(config.pipeline_job_root, job_id)
            images = list_job_images(images_dir)
            image_count = len(images)
            last_fingerprint, stable_rounds = stable_state.get(job_id, (tuple(), 0))

            if image_count >= config.min_img_count:
                fingerprint = build_job_image_fingerprint(images)
                if fingerprint == last_fingerprint:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                stable_state[job_id] = (fingerprint, stable_rounds)
                print(
                    f"⏳ 队列任务 {job_id}: {stable_rounds}/{config.stable_polls} | 图片数: {image_count}",
                    end="\r",
                )
                if state_store:
                    state_store.update(
                        phase="input",
                        status="running",
                        job_id=job_id,
                        message=f"正在等待队列任务 {job_id} 上传稳定",
                        metrics={
                            "queue_length": queue_length,
                            "uploaded_images": image_count,
                            "stable_rounds": stable_rounds,
                            "stable_polls": config.stable_polls,
                            "min_img_count": config.min_img_count,
                        },
                    paths={
                        "pipeline_job_root": str(config.pipeline_job_root),
                        "job_input_dir": str(images_dir),
                        "queue_job_id": job_id,
                    },
                )
                if stable_rounds >= config.stable_polls:
                    mark_job(config.pipeline_job_root, job_id, "running", "训练流程已开始消费该任务")
                    print(f"\n✅ 队列任务 {job_id} 上传稳定，共 {image_count} 张图片。")
                    return job, images
            else:
                stable_state[job_id] = (last_fingerprint, 0)
                if state_store:
                    state_store.update(
                        phase="input",
                        status="running",
                        job_id=job_id,
                        message=f"队列任务 {job_id} 等待更多图片",
                        metrics={
                            "queue_length": queue_length,
                            "uploaded_images": image_count,
                            "stable_rounds": 0,
                            "stable_polls": config.stable_polls,
                            "min_img_count": config.min_img_count,
                        },
                        paths={
                            "pipeline_job_root": str(config.pipeline_job_root),
                            "job_input_dir": str(images_dir),
                            "queue_job_id": job_id,
                        },
                    )
        time.sleep(config.poll_interval_sec)


def run_spann3r(
    config: PipelineConfig,
    scene_input_dir: Optional[Path] = None,
    scene_name: Optional[str] = None,
) -> Path:
    scene_input_dir = scene_input_dir or config.watch_dir
    scene_name = scene_name or scene_input_dir.name

    demo_command = [
        "python",
        "demo.py",
        "--demo_path",
        str(scene_input_dir),
        "--save_path",
        str(config.demo_output_root),
        "--ckpt_path",
        config.ckpt_path,
        "--device",
        config.device,
        "--kf_every",
        str(config.kf_every),
        "--conf_thresh",
        str(config.conf_thresh),
        "--resolution",
        str(config.resolution),
        "--voxel_size",
        str(config.voxel_size),
    ]
    if config.save_ori:
        demo_command.append("--save_ori")

    scene_output_dir = config.demo_output_root / scene_name
    if scene_output_dir.exists():
        shutil.rmtree(scene_output_dir)

    run_command(demo_command, cwd=config.spann3r_root)
    if not scene_output_dir.exists():
        raise FileNotFoundError(f"未找到 Spann3R 输出目录: {scene_output_dir}")
    return scene_output_dir


def resolve_latest_ply(scene_output_dir: Path) -> Path:
    candidates = sorted(
        scene_output_dir.glob("*.ply"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"未在 {scene_output_dir} 找到任何 .ply 文件")
    return candidates[0]


def resolve_pointcloud_variants(scene_output_dir: Path) -> Tuple[Path, Path]:
    raw_candidates = sorted(
        scene_output_dir.glob("*_raw.ply"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    downsampled_candidates = sorted(
        scene_output_dir.glob("*_downsampled_*.ply"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )

    latest = resolve_latest_ply(scene_output_dir)
    raw_path = raw_candidates[0] if raw_candidates else latest
    downsampled_path = downsampled_candidates[0] if downsampled_candidates else raw_path
    return raw_path, downsampled_path


def prepare_target_dataset(
    config: PipelineConfig,
    source_images_dir: Optional[Path] = None,
    target_data_dir: Optional[Path] = None,
) -> None:
    source_images_dir = source_images_dir or config.watch_dir
    target_data_dir = target_data_dir or config.target_data_dir

    if config.clear_target_before_run and target_data_dir.exists():
        shutil.rmtree(target_data_dir)
    (target_data_dir / "images").mkdir(parents=True, exist_ok=True)

    for image_path in list_images(source_images_dir):
        shutil.copy2(image_path, target_data_dir / "images" / image_path.name)


def run_conversion(
    config: PipelineConfig,
    scene_output_dir: Path,
    image_dir: Optional[Path] = None,
    output_json: Optional[Path] = None,
    ply_file_name: str = "init.ply",
    npy_name: Optional[str] = None,
) -> None:
    image_dir = image_dir or (config.target_data_dir / "images")
    output_json = output_json or (config.target_data_dir / "transforms.json")
    convert_command = [
        "python",
        "-m",
        "pipeline.spann3r_to_nerfstudio",
        "--scene_dir",
        str(scene_output_dir),
        "--img_dir",
        str(image_dir),
        "--output_json",
        str(output_json),
        "--ply_file_name",
        ply_file_name,
        "--model_resolution",
        str(config.resolution),
        "--kf_every",
        str(config.kf_every),
    ]
    if npy_name:
        convert_command.extend(["--npy_name", npy_name])
    run_command(convert_command, cwd=config.spann3r_root)


def copy_point_clouds(scene_output_dir: Path, target_data_dir: Path, scene_name: str) -> Tuple[str, str, str]:
    raw_source, downsampled_source = resolve_pointcloud_variants(scene_output_dir)

    raw_name = f"{scene_name}_raw.ply"
    downsampled_name = f"{scene_name}_downsampled.ply"
    train_name = f"{scene_name}_init.ply"

    raw_destination = target_data_dir / raw_name
    downsampled_destination = target_data_dir / downsampled_name
    train_destination = target_data_dir / train_name

    shutil.copy2(raw_source, raw_destination)
    shutil.copy2(downsampled_source, downsampled_destination)
    shutil.copy2(downsampled_source, train_destination)

    print(
        "📦 点云已同步: "
        f"raw={raw_source.name} -> {raw_destination.name}, "
        f"downsampled={downsampled_source.name} -> {downsampled_destination.name}, "
        f"train={train_destination.name}"
    )
    return raw_name, downsampled_name, train_name


def mark_latest_scene(scene_data_root: Path, scene_name: str) -> None:
    marker = scene_data_root / "LATEST_SCENE.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(scene_name + "\n", encoding="utf-8")


def archive_input_images(config: PipelineConfig) -> Dict[str, object]:
    images = list_images(config.watch_dir)
    part_files = sorted(config.watch_dir.glob("*.part")) if config.watch_dir.exists() else []
    manifest_file = config.watch_dir / "_upload_manifest.jsonl"
    if not images and not part_files and not manifest_file.exists():
        return {"mode": "empty", "deleted": 0, "archived": 0, "archive_dir": ""}

    if not config.archive_input:
        if not config.clear_input_after_snapshot:
            return {"mode": "keep", "deleted": 0, "archived": 0, "archive_dir": ""}
        deleted = 0
        for image_path in images:
            image_path.unlink(missing_ok=True)
            deleted += 1
        for part_path in part_files:
            part_path.unlink(missing_ok=True)
        manifest_file.unlink(missing_ok=True)
        print(f"🧹 已清理上传目录: {config.watch_dir} (删除 {deleted} 张图片)")
        return {"mode": "delete", "deleted": deleted, "archived": 0, "archive_dir": ""}

    archive_subdir = config.archive_dir / time.strftime("%Y%m%d_%H%M%S")
    archive_subdir.mkdir(parents=True, exist_ok=True)
    for image_path in images:
        shutil.move(str(image_path), archive_subdir / image_path.name)
    if manifest_file.exists():
        shutil.move(str(manifest_file), archive_subdir / manifest_file.name)
    print(f"🗄️ 已归档原始图片到: {archive_subdir}")
    return {"mode": "archive", "deleted": 0, "archived": len(images), "archive_dir": str(archive_subdir)}


def prune_child_dirs(root: Path, keep: int, protected_name: str = "") -> int:
    if keep <= 0 or not root.exists():
        return 0
    candidates = [item for item in root.iterdir() if item.is_dir() and item.name != protected_name]
    candidates.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)
    deleted = 0
    for old_dir in candidates[max(keep - 1, 0):]:
        shutil.rmtree(old_dir, ignore_errors=True)
        deleted += 1
    return deleted


def prune_old_assets(config: PipelineConfig, current_scene: str) -> None:
    deleted_scenes = prune_child_dirs(config.scene_data_root, config.max_scene_keep, current_scene)
    deleted_photo_sets = prune_child_dirs(config.test_photo_root, config.max_photo_sets_keep, current_scene)
    if deleted_scenes or deleted_photo_sets:
        print(
            "🧹 历史资产清理完成: "
            f"场景目录 {deleted_scenes} 个, 测试照片集 {deleted_photo_sets} 个"
        )


def build_ns_train_command(config: PipelineConfig, data_dir: Optional[Path] = None) -> List[str]:
    data_dir = data_dir or config.target_data_dir
    extra_args = shlex.split(config.ns_train_extra_args) if config.ns_train_extra_args else []
    extra_args = strip_ns_train_managed_args(extra_args)
    command = [
        "ns-train",
        "splatfacto",
        "--data",
        str(data_dir),
        "--max-num-iterations",
        str(config.ns_max_num_iterations),
        "--steps-per-save",
        str(config.ns_steps_per_save),
        "--viewer.websocket-port",
        str(config.viewer_port),
        "--viewer.quit-on-train-completion",
        "True" if config.ns_quit_on_train_completion else "False",
        "--pipeline.model.random-init",
        "False",
        "--vis",
        "viewer",
    ]
    if extra_args:
        command.extend(extra_args)
    command.extend([
        "nerfstudio-data",
        "--eval-mode",
        "fraction",
        "--train-split-fraction",
        str(config.train_split_fraction),
    ])
    return command


def strip_ns_train_managed_args(args: Sequence[str]) -> List[str]:
    managed = {
        "--max-num-iterations",
        "--steps-per-save",
        "--viewer.quit-on-train-completion",
    }
    stripped: List[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in managed:
            skip_next = True
            continue
        if any(arg.startswith(flag + "=") for flag in managed):
            continue
        stripped.append(arg)
    return stripped


def resolve_latest_ns_config(outputs_root: Path, scene_name: str, since_timestamp: float) -> Optional[Path]:
    if not outputs_root.exists():
        return None

    candidates: List[Tuple[int, float, Path]] = []
    for config_path in outputs_root.rglob("config.yml"):
        try:
            mtime = config_path.stat().st_mtime
        except OSError:
            continue
        score = 0
        path_text = str(config_path)
        if scene_name in path_text:
            score += 3
        if mtime >= (since_timestamp - 5):
            score += 2
        candidates.append((score, mtime, config_path))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def build_ns_export_command(config_path: Path, output_dir: Path, extra_args: str = "") -> List[str]:
    command: List[str] = [
        "ns-export",
        "gaussian-splat",
        "--load-config",
        str(config_path),
        "--output-dir",
        str(output_dir),
    ]
    if extra_args:
        command.extend(shlex.split(extra_args))
    return command


def crop_pointcloud_by_reference_bbox(
    source_ply: Path,
    reference_ply: Path,
    output_ply: Path,
    padding_ratio: float,
    distance_scale: float,
) -> Tuple[int, int, int, float]:
    source_cloud = o3d.io.read_point_cloud(str(source_ply))
    reference_cloud = o3d.io.read_point_cloud(str(reference_ply))

    source_count = len(source_cloud.points)
    reference_count = len(reference_cloud.points)
    if source_count <= 0:
        shutil.copy2(source_ply, output_ply)
        return 0, 0, 0, 0.0
    if reference_count <= 0:
        shutil.copy2(source_ply, output_ply)
        return source_count, source_count, source_count, 0.0

    source_points = np.asarray(source_cloud.points)
    reference_points = np.asarray(reference_cloud.points)
    ref_min = reference_points.min(axis=0)
    ref_max = reference_points.max(axis=0)
    ref_extent = np.maximum(ref_max - ref_min, 1e-6)
    padding = ref_extent * max(padding_ratio, 0.0)

    bbox_min = ref_min - padding
    bbox_max = ref_max + padding
    keep_mask = np.logical_and(source_points >= bbox_min, source_points <= bbox_max).all(axis=1)
    keep_indices = np.where(keep_mask)[0]

    if keep_indices.size <= 0:
        candidate_cloud = source_cloud
        bbox_count = source_count
    else:
        candidate_cloud = source_cloud.select_by_index(keep_indices.tolist())
        bbox_count = len(candidate_cloud.points)

    distance_threshold = 0.0
    final_cloud = candidate_cloud
    if len(candidate_cloud.points) > 0 and reference_count > 1:
        ref_nn = np.asarray(reference_cloud.compute_nearest_neighbor_distance())
        if ref_nn.size > 0:
            base_spacing = float(np.percentile(ref_nn, 90))
            distance_threshold = max(base_spacing * max(distance_scale, 0.1), 1e-4)
            distances = np.asarray(candidate_cloud.compute_point_cloud_distance(reference_cloud))
            keep_distance_indices = np.where(distances <= distance_threshold)[0]
            if keep_distance_indices.size > 0:
                final_cloud = candidate_cloud.select_by_index(keep_distance_indices.tolist())

    o3d.io.write_point_cloud(str(output_ply), final_cloud)
    return source_count, bbox_count, len(final_cloud.points), distance_threshold


def export_gaussian_artifacts(
    config: PipelineConfig,
    scene_name: str,
    scene_target_dir: Path,
    train_start_timestamp: float,
) -> Dict[str, str]:
    if not config.ns_export_after_train:
        print("⏭️ 已关闭 Gaussian 导出步骤（NS_EXPORT_AFTER_TRAIN=false）。")
        return {}

    config_path = resolve_latest_ns_config(config.ns_output_root, scene_name, train_start_timestamp)
    if not config_path:
        print(f"⚠️ 未找到可用训练配置，跳过 Gaussian 导出: root={config.ns_output_root}")
        return {}

    export_dir = scene_target_dir / config.gaussian_export_subdir
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    print(f"🧪 开始导出 Gaussian 点云: {config_path}")
    run_command(build_ns_export_command(config_path, export_dir, config.ns_export_extra_args), cwd=config.spann3r_root)

    exported_plys = sorted(
        export_dir.rglob("*.ply"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if not exported_plys:
        print(f"⚠️ Gaussian 导出完成但未发现 .ply: {export_dir}")
        return {}

    gaussian_raw_target = scene_target_dir / f"{scene_name}_gaussian_raw.ply"
    shutil.copy2(exported_plys[0], gaussian_raw_target)

    reference_ply = scene_target_dir / f"{scene_name}_downsampled.ply"
    gaussian_clipped_target = scene_target_dir / f"{scene_name}_gaussian_clipped.ply"
    if reference_ply.exists():
        source_count, bbox_count, final_count, distance_threshold = crop_pointcloud_by_reference_bbox(
            gaussian_raw_target,
            reference_ply,
            gaussian_clipped_target,
            config.gaussian_crop_padding_ratio,
            config.gaussian_ref_distance_scale,
        )
        print(
            "✂️ Gaussian 点云裁切完成: "
            f"source={source_count}, bbox={bbox_count}, final={final_count}, "
            f"padding_ratio={config.gaussian_crop_padding_ratio}, "
            f"distance_threshold={distance_threshold:.6f}"
        )
    else:
        shutil.copy2(gaussian_raw_target, gaussian_clipped_target)
        print(f"⚠️ 未找到参考下采样点云，已直接复制为 clipped: {gaussian_clipped_target.name}")

    print(
        "✅ Gaussian 点云导出完成: "
        f"raw={gaussian_raw_target.name}, clipped={gaussian_clipped_target.name}"
    )
    return {
        "gaussian_raw": str(gaussian_raw_target),
        "gaussian_clipped": str(gaussian_clipped_target),
        "gaussian_export_dir": str(export_dir),
    }


def terminate_conflicting_ns_train(viewer_port: int, keep_data_dir: Optional[Path] = None) -> List[int]:
    keep_data_dir = keep_data_dir.resolve() if keep_data_dir else None
    killed: List[int] = []
    try:
        output = subprocess.check_output(["ps", "-eo", "pid=,args="], text=True, errors="ignore")
    except Exception:
        return killed

    port_flag = f"--viewer.websocket-port {viewer_port}"
    keep_flag = f"--data {keep_data_dir}" if keep_data_dir else ""

    for row in output.splitlines():
        row = row.strip()
        if not row:
            continue
        try:
            pid_str, args = row.split(maxsplit=1)
            pid = int(pid_str)
        except ValueError:
            continue

        if "ns-train" not in args or port_flag not in args:
            continue
        if keep_flag and keep_flag in args:
            continue

        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except ProcessLookupError:
            continue

    return killed


def run_pipeline_once(
    config: PipelineConfig,
    state_store: Optional[PipelineStateStore] = None,
) -> None:
    state_store = state_store or PipelineStateStore()
    job_seed = f"{sanitize_name(config.scene_name_prefix)}_{time.strftime('%Y%m%d_%H%M%S')}"
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

    print("🧭 阶段切换: 输入监测")
    queue_job: Optional[Dict[str, object]] = None
    if config.queue_enabled:
        queue_job, images = wait_until_queued_job_stable(config, state_store=state_store)
    else:
        images = wait_until_upload_stable(config, state_store=state_store)
    scene_name = build_scene_name(config, images)
    if queue_job:
        queued_scene = str(queue_job.get("scene_name") or "").strip()
        if queued_scene:
            scene_name = sanitize_name(queued_scene)
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
            "queue_job_id": str(queue_job.get("id") or queue_job.get("job_id") or "") if queue_job else "",
        },
    )
    scene_photo_dir = snapshot_uploaded_images(config, images, scene_name)
    state_store.update(paths={"scene_photo_dir": str(scene_photo_dir)})

    print("🧭 阶段切换: Spann3R 重建")
    state_store.update(
        phase="spann3r",
        status="running",
        message="Spann3R 正在生成几何与相机位姿",
        paths={"scene_photo_dir": str(scene_photo_dir)},
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
    prune_old_assets(config, scene_name)

    print(f"✅ 训练数据已就绪: {scene_target_dir}")
    stale_pids = terminate_conflicting_ns_train(config.viewer_port, keep_data_dir=scene_target_dir)
    if stale_pids:
        print(f"🧹 已停止占用 Viewer 端口 {config.viewer_port} 的旧训练进程: {stale_pids}")
    print("🧭 阶段切换: Gaussian 训练/导出")
    print("🔥 启动 Nerfstudio 训练...")
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
    archive_summary = archive_input_images(config)
    state_store.update(
        phase="completed",
        status="completed",
        message="训练与导出完成",
        metrics={"step": config.ns_max_num_iterations, "percent": 100},
        artifacts=gaussian_artifacts,
        paths={"upload_cleanup": archive_summary},
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


def main() -> None:
    config = PipelineConfig.from_env()
    state_store = PipelineStateStore()
    printable = asdict(config)
    printable["watch_dir"] = str(config.watch_dir)
    printable["spann3r_root"] = str(config.spann3r_root)
    printable["demo_output_root"] = str(config.demo_output_root)
    printable["target_data_dir"] = str(config.target_data_dir)
    printable["scene_data_root"] = str(config.scene_data_root)
    printable["test_photo_root"] = str(config.test_photo_root)
    printable["archive_dir"] = str(config.archive_dir)
    printable["ns_output_root"] = str(config.ns_output_root)
    print("📋 当前参数:")
    for key in sorted(printable):
        print(f"  - {key}: {printable[key]}")

    while True:
        try:
            run_pipeline_once(config, state_store=state_store)
            if config.run_once:
                break
        except Exception as error:
            print(f"\n❌ 流水线异常: {error}")
            failed_state = state_store.fail(error)
            paths = failed_state.get("paths") if isinstance(failed_state.get("paths"), dict) else {}
            queue_job_id = str(paths.get("queue_job_id") or "")
            if config.queue_enabled and queue_job_id:
                mark_job(
                    config.pipeline_job_root,
                    queue_job_id,
                    "failed",
                    "训练失败",
                    error=str(error),
                )
            if config.run_once:
                raise
            print(f"⏳ {config.retry_interval_sec} 秒后重试...")
            time.sleep(config.retry_interval_sec)


if __name__ == "__main__":
    main()
