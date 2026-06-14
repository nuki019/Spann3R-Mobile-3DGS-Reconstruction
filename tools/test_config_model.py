"""Offline checks for backend dashboard config helpers."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.config_model import (  # noqa: E402
    get_config_bool,
    get_config_path,
    parse_bool_value,
    parse_env_text,
    read_config_file,
    render_env_text,
    write_config_file,
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


def test_parse_env_text() -> None:
    defaults = {
        "NS_MAX_NUM_ITERATIONS": "1000",
        "PIPELINE_QUEUE_ENABLED": "true",
        "WATCH_DIR": "/root/autodl-tmp/input_images",
    }
    values = parse_env_text(
        """
        # ignored comment
        NS_MAX_NUM_ITERATIONS=1200
        UNKNOWN_SECRET=do-not-keep
        PIPELINE_QUEUE_ENABLED = false
        WATCH_DIR=/tmp/input images
        """,
        defaults,
    )
    assert_equal(values["NS_MAX_NUM_ITERATIONS"], "1200", "known values should override defaults")
    assert_equal(values["PIPELINE_QUEUE_ENABLED"], "false", "spaces around key should be tolerated")
    assert_equal(values["WATCH_DIR"], "/tmp/input images", "values should preserve internal spaces")
    assert_true("UNKNOWN_SECRET" not in values, "unknown keys must be ignored")
    print("[OK] config env parsing")


def test_render_and_file_roundtrip() -> None:
    defaults = {
        "A": "default-a",
        "B": "default-b",
        "C": "default-c",
    }
    rendered = render_env_text({"B": "custom-b"}, defaults, ["A", "B", "C"], header="# header")
    assert_equal(
        rendered,
        "# header\nA=default-a\nB=custom-b\nC=default-c\n",
        "rendered env text should be stable and fill defaults",
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / ".env.pipeline.4090"
        missing = read_config_file(path, defaults)
        assert_equal(missing, defaults, "missing config file should return defaults")

        write_config_file(path, {"A": "custom-a"}, defaults, ["A", "B", "C"])
        loaded = read_config_file(path, defaults)
        assert_equal(loaded["A"], "custom-a", "written config should be readable")
        assert_equal(loaded["B"], "default-b", "missing written values should fall back to defaults")
    print("[OK] config render and file roundtrip")


def test_bool_and_path_helpers() -> None:
    for value in ["1", "true", "TRUE", "yes", "y", "on"]:
        assert_true(parse_bool_value(value, False), f"{value} should parse as true")
    for value in ["0", "false", "FALSE", "no", "n", "off"]:
        assert_true(not parse_bool_value(value, True), f"{value} should parse as false")
    assert_true(parse_bool_value("", True), "empty bool should use default true")
    assert_true(not parse_bool_value("maybe", False), "unknown bool should use default false")

    values = {"ENABLED": "yes", "DISABLED": "no", "ROOT": "."}
    assert_true(get_config_bool(values, "ENABLED", False), "get_config_bool true parse failed")
    assert_true(not get_config_bool(values, "DISABLED", True), "get_config_bool false parse failed")
    assert_true(get_config_path(values, "ROOT", Path("/tmp")).is_absolute(), "resolved config path should be absolute")
    print("[OK] config bool and path helpers")


def main() -> None:
    test_parse_env_text()
    test_render_and_file_roundtrip()
    test_bool_and_path_helpers()
    print("[OK] config model checks passed")


if __name__ == "__main__":
    main()
