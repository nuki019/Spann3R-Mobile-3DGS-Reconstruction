"""Offline checks for managed Nerfstudio command construction."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pipeline.command_model import (  # noqa: E402
    build_ns_export_command,
    build_ns_train_command,
    strip_ns_export_managed_args,
    strip_ns_train_managed_args,
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


def count_arg(command: list[str], flag: str) -> int:
    return sum(1 for item in command if item == flag or item.startswith(flag + "="))


def value_after(command: list[str], flag: str) -> str:
    try:
        return command[command.index(flag) + 1]
    except (ValueError, IndexError):
        fail(f"missing command flag or value: {flag}")


def test_strip_train_managed_args() -> None:
    args = [
        "--data",
        "/tmp/other_scene",
        "--max-num-iterations",
        "60",
        "--steps-per-save=60",
        "--viewer.websocket-port",
        "7007",
        "--viewer.quit-on-train-completion=False",
        "--pipeline.model.random-init",
        "True",
        "--vis=wandb",
        "--output-dir",
        "/tmp/ns",
        "--experiment-name",
        "demo",
    ]
    stripped = strip_ns_train_managed_args(args)
    assert_equal(
        stripped,
        ["--output-dir", "/tmp/ns", "--experiment-name", "demo"],
        "train stripper should remove only managed value flags",
    )
    print("[OK] command model strips managed train args")


def test_build_train_command_locks_delivery_defaults() -> None:
    data_dir = Path("/data/scene_a")
    command = build_ns_train_command(
        data_dir=data_dir,
        max_num_iterations=1000,
        steps_per_save=1000,
        viewer_port=6006,
        quit_on_train_completion=True,
        train_split_fraction=0.92,
        extra_args=(
            "--data /tmp/other_scene "
            "--max-num-iterations 60 "
            "--steps-per-save=60 "
            "--viewer.websocket-port 7007 "
            "--viewer.quit-on-train-completion=False "
            "--pipeline.model.random-init True "
            "--vis wandb "
            "--output-dir /tmp/ns "
            "--experiment-name demo"
        ),
    )

    assert_equal(command[:2], ["ns-train", "splatfacto"], "train command should use splatfacto")
    assert_equal(value_after(command, "--data"), str(data_dir), "train data dir changed")
    assert_equal(count_arg(command, "--data"), 1, "managed train data dir should appear once")
    assert_equal(value_after(command, "--max-num-iterations"), "1000", "train iteration lock changed")
    assert_equal(value_after(command, "--steps-per-save"), "1000", "checkpoint step lock changed")
    assert_equal(value_after(command, "--viewer.websocket-port"), "6006", "viewer port lock changed")
    assert_equal(
        value_after(command, "--viewer.quit-on-train-completion"),
        "True",
        "viewer completion behavior changed",
    )
    assert_equal(value_after(command, "--pipeline.model.random-init"), "False", "random-init lock changed")
    assert_equal(value_after(command, "--vis"), "viewer", "viewer visualization lock changed")
    assert_equal(count_arg(command, "--max-num-iterations"), 1, "managed max iterations should appear once")
    assert_equal(count_arg(command, "--steps-per-save"), 1, "managed save steps should appear once")
    assert_equal(count_arg(command, "--viewer.websocket-port"), 1, "managed viewer port should appear once")
    assert_true("--output-dir" in command and "/tmp/ns" in command, "safe train extra args should be preserved")
    assert_true("--experiment-name" in command and "demo" in command, "safe named train args should be preserved")

    data_index = command.index("nerfstudio-data")
    assert_equal(
        command[data_index + 1 :],
        ["--eval-mode", "fraction", "--train-split-fraction", "0.92"],
        "data parser args changed",
    )
    print("[OK] command model builds locked train command")


def test_build_train_command_false_quit_flag() -> None:
    command = build_ns_train_command(
        data_dir=Path("/data/scene_b"),
        max_num_iterations=1000,
        steps_per_save=1000,
        viewer_port=6006,
        quit_on_train_completion=False,
        train_split_fraction=1.0,
    )
    assert_equal(
        value_after(command, "--viewer.quit-on-train-completion"),
        "False",
        "quit flag should reflect configuration",
    )
    print("[OK] command model preserves configured quit flag")


def test_strip_and_build_export_command() -> None:
    stripped = strip_ns_export_managed_args(
        [
            "--load-config",
            "/tmp/other.yml",
            "--output-dir=/tmp/other",
            "--num-points",
            "400000",
        ]
    )
    assert_equal(stripped, ["--num-points", "400000"], "export stripper should keep safe export args")

    config_path = Path("/runs/scene/config.yml")
    output_dir = Path("/exports/scene_a")
    command = build_ns_export_command(
        config_path,
        output_dir,
        "--load-config /tmp/other.yml --output-dir=/tmp/other --num-points 400000",
    )
    assert_equal(command[:2], ["ns-export", "gaussian-splat"], "export command type changed")
    assert_equal(value_after(command, "--load-config"), str(config_path), "export config lock changed")
    assert_equal(value_after(command, "--output-dir"), str(output_dir), "export output lock changed")
    assert_equal(count_arg(command, "--load-config"), 1, "managed export config should appear once")
    assert_equal(count_arg(command, "--output-dir"), 1, "managed export output should appear once")
    assert_true("--num-points" in command and "400000" in command, "safe export extra args should be preserved")
    print("[OK] command model builds locked export command")


def main() -> None:
    test_strip_train_managed_args()
    test_build_train_command_locks_delivery_defaults()
    test_build_train_command_false_quit_flag()
    test_strip_and_build_export_command()
    print("[OK] command model checks passed")


if __name__ == "__main__":
    main()
