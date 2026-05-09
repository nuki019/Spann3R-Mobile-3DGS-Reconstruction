import argparse
import json
from pathlib import Path
from typing import List, Tuple

import numpy as np
from PIL import Image

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"}
DEFAULT_SPANN3R_WIDTH = 224
DEFAULT_SPANN3R_HEIGHT = 224


def list_images(image_dir: Path) -> List[Path]:
    images = [p for p in image_dir.iterdir() if p.is_file() and p.suffix in VALID_EXTENSIONS]
    images.sort(key=lambda p: (p.stat().st_mtime_ns, p.name))
    return images


def select_pose_aligned_images(images: List[Path], pose_count: int, kf_every: int) -> List[Path]:
    if kf_every <= 0:
        raise ValueError("kf_every 必须 >= 1")
    if not images:
        return []
    if pose_count <= 0:
        return []

    sampled = images[::kf_every]
    if not sampled:
        sampled = images[:1]

    if pose_count <= len(sampled):
        return sampled[:pose_count]

    # 兜底策略：当历史数据的位姿数量与采样参数不一致时，退化为顺序匹配。
    if pose_count <= len(images):
        print(
            "⚠️ 位姿数量超过按 kf_every 采样后的图片数量，"
            "已回退为按时间顺序匹配前 N 张图片。"
        )
        return images[:pose_count]

    return images


def find_npy(scene_dir: Path, image_dir: Path, npy_name: str = "") -> Path:
    npy_name = npy_name.strip()
    if npy_name:
        target_name = npy_name if npy_name.endswith(".npy") else f"{npy_name}.npy"
        preferred = scene_dir / target_name
        if preferred.exists():
            return preferred

    scene_name = image_dir.name
    exact_match = scene_dir / f"{scene_name}.npy"
    if exact_match.exists():
        return exact_match

    candidates = sorted(scene_dir.glob("*.npy"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"未在 {scene_dir} 中找到 .npy 文件")
    return candidates[0]


def infer_target_resolution(images: List[Path]) -> Tuple[int, int]:
    with Image.open(images[0]) as image:
        width, height = image.size
    return width, height


def infer_scale_factor(target_w: int, target_h: int, model_resolution: int) -> float:
    min_side = min(target_w, target_h)
    if min_side <= 0:
        raise ValueError("图片尺寸非法，最短边必须大于 0")
    return float(model_resolution) / float(min_side)


def convert(
    scene_dir: Path,
    image_dir: Path,
    output_json: Path,
    ply_file_name: str,
    npy_name: str = "",
    model_resolution: int = DEFAULT_SPANN3R_WIDTH,
    kf_every: int = 1,
) -> None:
    all_images = list_images(image_dir)
    if not all_images:
        raise ValueError(f"在 {image_dir} 未找到图片文件")

    npy_path = find_npy(scene_dir, image_dir, npy_name=npy_name)
    print(f"正在转换: {npy_path}")
    data = np.load(npy_path, allow_pickle=True).item()

    poses = data["poses_all"]
    intrinsic = data["intrinsic"]
    pose_count = int(poses.shape[0])

    images = select_pose_aligned_images(all_images, pose_count=pose_count, kf_every=kf_every)
    if not images:
        raise ValueError("图片与位姿匹配失败：未选出可用图片")

    target_w, target_h = infer_target_resolution(images)

    # Spann3R 的焦距是基于模型输入分辨率（通常 224）估计得到的，
    # 对原图恢复时必须使用统一缩放因子，不能按宽高分别缩放。
    scale_factor = infer_scale_factor(target_w, target_h, model_resolution)
    focal = float(intrinsic[0, 0]) / scale_factor
    fl_x = focal
    fl_y = focal
    cx = target_w / 2.0
    cy = target_h / 2.0

    flip_mat = np.array(
        [
            [1, 0, 0, 0],
            [0, -1, 0, 0],
            [0, 0, -1, 0],
            [0, 0, 0, 1],
        ],
        dtype=np.float32,
    )

    frame_count = min(len(images), pose_count)
    frames = []
    for index in range(frame_count):
        c2w = poses[index]
        c2w_opengl = c2w @ flip_mat
        frames.append(
            {
                "file_path": f"images/{images[index].name}",
                "transform_matrix": c2w_opengl.tolist(),
            }
        )

    payload = {
        "fl_x": fl_x,
        "fl_y": fl_y,
        "cx": cx,
        "cy": cy,
        "w": target_w,
        "h": target_h,
        "k1": 0,
        "k2": 0,
        "p1": 0,
        "p2": 0,
        "camera_model": "OPENCV",
        "ply_file_path": ply_file_name,
        "frames": frames,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with output_json.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=4)
    print(f"已输出 transforms.json: {output_json}")
    print(
        f"匹配帧数: {frame_count} / 原图总数: {len(all_images)} / 采样后图片数: {len(images)} / 位姿总数: {pose_count}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert Spann3R npy output to Nerfstudio transforms.json")
    parser.add_argument("--scene_dir", type=Path, required=True, help="Spann3R 输出目录，包含 .npy")
    parser.add_argument("--img_dir", type=Path, required=True, help="用于训练的图片目录")
    parser.add_argument(
        "--output_json",
        type=Path,
        default=None,
        help="输出 transforms.json 路径，默认写入 scene_dir/transforms.json",
    )
    parser.add_argument(
        "--ply_file_name",
        type=str,
        default="init.ply",
        help="写入 transforms.json 的 ply_file_path 字段",
    )
    parser.add_argument(
        "--npy_name",
        type=str,
        default="",
        help="可选，指定要使用的 npy 文件名（可带或不带 .npy 后缀）",
    )
    parser.add_argument(
        "--model_resolution",
        type=int,
        default=DEFAULT_SPANN3R_WIDTH,
        help="Spann3R 推理分辨率（默认 224）",
    )
    parser.add_argument(
        "--kf_every",
        type=int,
        default=1,
        help="与 demo.py 一致的关键帧采样间隔（默认 1）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_json = args.output_json or args.scene_dir / "transforms.json"
    convert(
        args.scene_dir,
        args.img_dir,
        output_json,
        args.ply_file_name,
        npy_name=args.npy_name,
        model_resolution=args.model_resolution,
        kf_every=args.kf_every,
    )


if __name__ == "__main__":
    main()
