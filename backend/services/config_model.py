"""Shared configuration file helpers for the backend dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Mapping


TRUE_VALUES = {"1", "true", "yes", "y", "on"}
FALSE_VALUES = {"0", "false", "no", "n", "off"}


def parse_env_text(text: str, defaults: Mapping[str, str]) -> Dict[str, str]:
    values = dict(defaults)
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in values:
            values[key] = value.strip()
    return values


def read_config_file(path: Path, defaults: Mapping[str, str]) -> Dict[str, str]:
    if not path.exists():
        return dict(defaults)
    return parse_env_text(path.read_text(encoding="utf-8", errors="ignore"), defaults)


def render_env_text(
    values: Mapping[str, str],
    defaults: Mapping[str, str],
    editable_keys: Iterable[str],
    header: str = "# Auto-managed by backend_dashboard.py",
) -> str:
    lines = [header]
    for key in editable_keys:
        lines.append(f"{key}={values.get(key, defaults[key])}")
    return "\n".join(lines) + "\n"


def write_config_file(
    path: Path,
    values: Mapping[str, str],
    defaults: Mapping[str, str],
    editable_keys: Iterable[str],
) -> None:
    path.write_text(render_env_text(values, defaults, editable_keys), encoding="utf-8")


def merge_editable_values(
    current_values: Mapping[str, str],
    updates: Mapping[str, object],
    editable_keys: Iterable[str],
) -> Dict[str, str]:
    merged = dict(current_values)
    editable = set(editable_keys)
    for key, value in updates.items():
        if key in editable:
            merged[key] = str(value).strip()
    return merged


def parse_bool_value(value: object, default: bool) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return default
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def get_config_bool(values: Mapping[str, str], key: str, default: bool) -> bool:
    return parse_bool_value(values.get(key, ""), default)


def get_config_path(values: Mapping[str, str], key: str, fallback: Path) -> Path:
    return Path(values.get(key, str(fallback))).resolve()
