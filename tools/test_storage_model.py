"""Offline checks for pipeline storage and cleanup helpers."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pipeline.storage_model import (  # noqa: E402
    build_image_fingerprint,
    build_scene_name,
    cleanup_upload_inputs,
    list_images,
    mark_latest_scene,
    prune_child_dirs,
    sanitize_scene_name,
    snapshot_images,
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


def write_file(path: Path, content: bytes, mtime_ns: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    seconds = mtime_ns / 1_000_000_000
    import os

    os.utime(path, ns=(mtime_ns, mtime_ns))
    assert_true(path.stat().st_mtime_ns == mtime_ns or path.stat().st_mtime >= seconds, "mtime setup failed")
    return path


def set_dir_mtime(path: Path, mtime_ns: int) -> None:
    import os

    os.utime(path, ns=(mtime_ns, mtime_ns))


def test_image_listing_and_scene_name() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        newer = write_file(root / "b.JPG", b"b", 2_000_000_000)
        older = write_file(root / "a.jpg", b"a", 1_000_000_000)
        write_file(root / "notes.txt", b"skip", 3_000_000_000)

        images = list_images(root)
        assert_equal(images, [older, newer], "images should be sorted by mtime then name")
        fingerprint = build_image_fingerprint(images)
        assert_equal(fingerprint[0][0], "a.jpg", "fingerprint should include image names")

        assert_equal(sanitize_scene_name(" demo scene/01 "), "demo_scene_01", "scene name sanitization failed")
        assert_equal(sanitize_scene_name("!!!"), "scene", "empty scene name should fallback")

        scene_name = build_scene_name("demo scene", images, timestamp="20260614_120000")
        assert_true(scene_name.startswith("demo_scene_20260614_120000_"), "scene name prefix/timestamp changed")
        assert_equal(len(scene_name.rsplit("_", 1)[-1]), 8, "scene digest should be 8 chars")
    print("[OK] storage image listing and scene names")


def test_snapshot_latest_and_prune() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        source = root / "source"
        image = write_file(source / "frame.jpg", b"frame", 1_000_000_000)
        target_root = root / "photos"
        stale_target = target_root / "scene_a"
        stale_target.mkdir(parents=True)
        (stale_target / "old.jpg").write_bytes(b"old")

        snapshot_dir = snapshot_images([image], target_root, "scene_a")
        assert_true((snapshot_dir / "frame.jpg").exists(), "snapshot should copy image")
        assert_true(not (snapshot_dir / "old.jpg").exists(), "snapshot should replace old scene dir")

        scene_root = root / "scenes"
        mark_latest_scene(scene_root, "scene_a")
        assert_equal((scene_root / "LATEST_SCENE.txt").read_text(encoding="utf-8"), "scene_a\n", "latest scene marker changed")

        for index, name in enumerate(["old", "middle", "new", "protected"]):
            child = scene_root / name
            child.mkdir(parents=True, exist_ok=True)
            write_file(child / "marker.txt", name.encode("utf-8"), (index + 1) * 1_000_000_000)
            set_dir_mtime(child, (index + 1) * 1_000_000_000)
        deleted = prune_child_dirs(scene_root, keep=2, protected_name="protected")
        assert_equal(deleted, 2, "prune should delete older unprotected dirs")
        assert_true((scene_root / "new").exists(), "newest dir should be kept")
        assert_true((scene_root / "protected").exists(), "protected dir should be kept")
    print("[OK] storage snapshot/latest/prune")


def test_upload_cleanup_modes() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)

        empty = cleanup_upload_inputs(root / "missing", root / "archive", False, True)
        assert_equal(empty["mode"], "empty", "missing upload dir should be empty")

        keep_dir = root / "keep"
        write_file(keep_dir / "frame.jpg", b"frame", 1_000_000_000)
        keep = cleanup_upload_inputs(keep_dir, root / "archive", False, False)
        assert_equal(keep["mode"], "keep", "keep mode changed")
        assert_true((keep_dir / "frame.jpg").exists(), "keep mode should preserve image")

        delete_dir = root / "delete"
        write_file(delete_dir / "frame.jpg", b"frame", 1_000_000_000)
        write_file(delete_dir / "upload.part", b"part", 1_000_000_000)
        (delete_dir / "_upload_manifest.jsonl").write_text("{}\n", encoding="utf-8")
        deleted = cleanup_upload_inputs(delete_dir, root / "archive", False, True)
        assert_equal(deleted["mode"], "delete", "delete cleanup mode changed")
        assert_equal(deleted["deleted"], 1, "delete mode should count removed images")
        assert_true(not any(delete_dir.iterdir()), "delete mode should clear images, parts, and manifest")

        archive_dir = root / "archive_input"
        write_file(archive_dir / "frame.jpg", b"frame", 1_000_000_000)
        write_file(archive_dir / "upload.part", b"part", 1_000_000_000)
        (archive_dir / "_upload_manifest.jsonl").write_text("{}\n", encoding="utf-8")
        archived = cleanup_upload_inputs(archive_dir, root / "archives", True, True, timestamp="20260614_120000")
        assert_equal(archived["mode"], "archive", "archive cleanup mode changed")
        archive_subdir = Path(str(archived["archive_dir"]))
        assert_true((archive_subdir / "frame.jpg").exists(), "archive should move image")
        assert_true((archive_subdir / "upload.part").exists(), "archive should move part file")
        assert_true((archive_subdir / "_upload_manifest.jsonl").exists(), "archive should move manifest")
        assert_true(not any(archive_dir.iterdir()), "archive source should be empty")
    print("[OK] storage upload cleanup modes")


def main() -> None:
    test_image_listing_and_scene_name()
    test_snapshot_latest_and_prune()
    test_upload_cleanup_modes()
    print("[OK] storage model checks passed")


if __name__ == "__main__":
    main()
