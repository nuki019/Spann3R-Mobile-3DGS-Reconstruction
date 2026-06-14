"""Pure Nerfstudio command construction helpers."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Iterable, List, Sequence


NS_TRAIN_MANAGED_VALUE_FLAGS = {
    "--data",
    "--max-num-iterations",
    "--steps-per-save",
    "--viewer.websocket-port",
    "--viewer.quit-on-train-completion",
    "--pipeline.model.random-init",
    "--vis",
}

NS_EXPORT_MANAGED_VALUE_FLAGS = {
    "--load-config",
    "--output-dir",
}


def strip_managed_value_args(args: Sequence[str], managed_flags: Iterable[str]) -> List[str]:
    managed = set(managed_flags)
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


def strip_ns_train_managed_args(args: Sequence[str]) -> List[str]:
    return strip_managed_value_args(args, NS_TRAIN_MANAGED_VALUE_FLAGS)


def strip_ns_export_managed_args(args: Sequence[str]) -> List[str]:
    return strip_managed_value_args(args, NS_EXPORT_MANAGED_VALUE_FLAGS)


def build_ns_train_command(
    data_dir: Path,
    max_num_iterations: int,
    steps_per_save: int,
    viewer_port: int,
    quit_on_train_completion: bool,
    train_split_fraction: float,
    extra_args: str = "",
) -> List[str]:
    parsed_extra_args = shlex.split(extra_args) if extra_args else []
    parsed_extra_args = strip_ns_train_managed_args(parsed_extra_args)
    command = [
        "ns-train",
        "splatfacto",
        "--data",
        str(data_dir),
        "--max-num-iterations",
        str(max_num_iterations),
        "--steps-per-save",
        str(steps_per_save),
        "--viewer.websocket-port",
        str(viewer_port),
        "--viewer.quit-on-train-completion",
        "True" if quit_on_train_completion else "False",
        "--pipeline.model.random-init",
        "False",
        "--vis",
        "viewer",
    ]
    if parsed_extra_args:
        command.extend(parsed_extra_args)
    command.extend(
        [
            "nerfstudio-data",
            "--eval-mode",
            "fraction",
            "--train-split-fraction",
            str(train_split_fraction),
        ]
    )
    return command


def build_ns_export_command(config_path: Path, output_dir: Path, extra_args: str = "") -> List[str]:
    command = [
        "ns-export",
        "gaussian-splat",
        "--load-config",
        str(config_path),
        "--output-dir",
        str(output_dir),
    ]
    parsed_extra_args = shlex.split(extra_args) if extra_args else []
    parsed_extra_args = strip_ns_export_managed_args(parsed_extra_args)
    if parsed_extra_args:
        command.extend(parsed_extra_args)
    return command
