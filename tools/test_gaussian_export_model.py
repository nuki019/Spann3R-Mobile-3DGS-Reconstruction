"""Offline checks for manual Gaussian export helpers."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.gaussian_export_model import (  # noqa: E402
    apply_gaussian_export_config,
    latest_scene_dir,
)


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def assert_equal(actual: object, expected: object, message: str) -> None:
    if actual != expected:
        fail(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(value: object, message: str) -> None:
    if not value:
        fail(message)


def test_apply_gaussian_export_config_defaults() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        config = apply_gaussian_export_config(
            SimpleNamespace(),
            {},
            root / "Spann3R",
            root / "scenes",
            root / "outputs",
        )

        assert_equal(config.spann3r_root, (root / "Spann3R").resolve(), "spann3r root changed")
        assert_equal(config.scene_data_root, (root / "scenes").resolve(), "scene root fallback changed")
        assert_equal(config.ns_output_root, (root / "outputs").resolve(), "output root fallback changed")
        assert_true(config.ns_export_after_train, "export after train should default true")
        assert_equal(config.gaussian_export_subdir, "gaussian_export", "export subdir fallback changed")
        assert_equal(config.gaussian_crop_padding_ratio, 0.03, "crop padding fallback changed")
        assert_equal(config.gaussian_ref_distance_scale, 4.0, "reference distance fallback changed")
        assert_equal(config.ns_export_extra_args, "", "extra export args fallback changed")
    print("[OK] gaussian export defaults")


def test_apply_gaussian_export_config_overrides() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        values = {
            "SCENE_DATA_ROOT": str(root / "custom scenes"),
            "NS_OUTPUT_ROOT": str(root / "custom outputs"),
            "NS_EXPORT_AFTER_TRAIN": "no",
            "GAUSSIAN_EXPORT_SUBDIR": " custom_export ",
            "GAUSSIAN_CROP_PADDING_RATIO": "0.12",
            "GAUSSIAN_REF_DISTANCE_SCALE": "2.5",
            "NS_EXPORT_EXTRA_ARGS": " --obb_center 0 0 0 ",
        }
        config = apply_gaussian_export_config(
            SimpleNamespace(),
            values,
            root,
            root / "scenes",
            root / "outputs",
        )

        assert_equal(config.scene_data_root, (root / "custom scenes").resolve(), "scene root override changed")
        assert_equal(config.ns_output_root, (root / "custom outputs").resolve(), "output root override changed")
        assert_true(not config.ns_export_after_train, "export after train bool override changed")
        assert_equal(config.gaussian_export_subdir, "custom_export", "export subdir should be trimmed")
        assert_equal(config.gaussian_crop_padding_ratio, 0.12, "crop padding override changed")
        assert_equal(config.gaussian_ref_distance_scale, 2.5, "reference distance override changed")
        assert_equal(config.ns_export_extra_args, "--obb_center 0 0 0", "extra args should be trimmed")
    print("[OK] gaussian export overrides")


def test_empty_export_subdir_and_scene_dir() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        config = apply_gaussian_export_config(
            SimpleNamespace(),
            {"GAUSSIAN_EXPORT_SUBDIR": "   "},
            root,
            root / "scenes",
            root / "outputs",
        )
        assert_equal(config.gaussian_export_subdir, "gaussian_export", "blank export subdir should use fallback")
        assert_equal(
            latest_scene_dir(config.scene_data_root, "scene_20260614"),
            config.scene_data_root / "scene_20260614",
            "latest scene dir changed",
        )
    print("[OK] gaussian export scene dir")


def main() -> None:
    test_apply_gaussian_export_config_defaults()
    test_apply_gaussian_export_config_overrides()
    test_empty_export_subdir_and_scene_dir()
    print("[OK] gaussian export model checks passed")


if __name__ == "__main__":
    main()
