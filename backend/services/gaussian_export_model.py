"""Pure helpers for manual Gaussian export configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from services.config_model import get_config_bool, get_config_path


def apply_gaussian_export_config(
    config: Any,
    values: Mapping[str, str],
    root_dir: Path,
    scene_data_root_fallback: Path,
    ns_output_root_fallback: Path,
) -> Any:
    """Apply dashboard-editable export values to a PipelineConfig-like object."""

    config.spann3r_root = Path(root_dir).resolve()
    config.scene_data_root = get_config_path(values, "SCENE_DATA_ROOT", scene_data_root_fallback)
    config.ns_output_root = get_config_path(values, "NS_OUTPUT_ROOT", ns_output_root_fallback)
    config.ns_export_after_train = get_config_bool(values, "NS_EXPORT_AFTER_TRAIN", True)
    config.gaussian_export_subdir = (
        str(values.get("GAUSSIAN_EXPORT_SUBDIR", "gaussian_export")).strip()
        or "gaussian_export"
    )
    config.gaussian_crop_padding_ratio = float(
        values.get("GAUSSIAN_CROP_PADDING_RATIO", "0.03")
    )
    config.gaussian_ref_distance_scale = float(
        values.get("GAUSSIAN_REF_DISTANCE_SCALE", "4.0")
    )
    config.ns_export_extra_args = str(values.get("NS_EXPORT_EXTRA_ARGS", "")).strip()
    return config


def latest_scene_dir(scene_data_root: Path, latest_scene: str) -> Path:
    return Path(scene_data_root) / latest_scene
