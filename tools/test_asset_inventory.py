"""Offline checks for dashboard filesystem inventory helpers."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.asset_inventory import (  # noqa: E402
    build_scenes_summary_payload,
    build_uploads_summary_payload,
    discover_archive_dirs,
    discover_photo_scenes,
    discover_scene_datasets,
    discover_uploaded_images,
    list_images,
    read_latest_scene,
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


def write_file(path: Path, payload: bytes, mtime: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    os.utime(path, (mtime, mtime))
    return path


def set_mtime(path: Path, mtime: int) -> None:
    os.utime(path, (mtime, mtime))


def test_uploaded_images() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        old = write_file(root / "a.jpg", b"old", 1_700_000_001)
        new = write_file(root / "b.PNG", b"newer", 1_700_000_003)
        write_file(root / "notes.txt", b"skip", 1_700_000_004)

        images = list_images(root)
        assert_equal(images, [new, old], "images should be sorted newest first")

        payload = discover_uploaded_images(root)
        assert_equal([item["name"] for item in payload], ["b.PNG", "a.jpg"], "uploaded image names changed")
        assert_equal(payload[0]["size_bytes"], "5", "uploaded image size changed")
        assert_true(payload[0]["mtime"].startswith("2023-"), "mtime should be formatted")
    print("[OK] asset inventory uploaded images")


def test_archive_dirs() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        older = root / "archive_old"
        newer = root / "archive_new"
        write_file(older / "frame.jpg", b"jpg", 1_700_000_001)
        write_file(older / "upload.part", b"part", 1_700_000_001)
        write_file(newer / "frame.png", b"png", 1_700_000_002)
        write_file(newer / "notes.txt", b"txt", 1_700_000_002)
        set_mtime(older, 1_700_000_001)
        set_mtime(newer, 1_700_000_002)

        archives = discover_archive_dirs(root)
        assert_equal([item["name"] for item in archives], ["archive_new", "archive_old"], "archives should be newest first")
        assert_equal(archives[0]["image_count"], "1", "archive image count changed")
        assert_equal(archives[0]["file_count"], "2", "archive file count changed")
        assert_equal(archives[0]["size_bytes"], "6", "archive total size changed")
    print("[OK] asset inventory archives")


def test_photo_scenes_and_datasets() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        photo_root = root / "photos"
        scene_root = root / "scenes"

        write_file(photo_root / "scene_old" / "a.jpg", b"a", 1_700_000_001)
        write_file(photo_root / "scene_new" / "a.jpg", b"a", 1_700_000_002)
        write_file(photo_root / "scene_new" / "b.jpeg", b"b", 1_700_000_002)
        set_mtime(photo_root / "scene_old", 1_700_000_001)
        set_mtime(photo_root / "scene_new", 1_700_000_002)

        photos = discover_photo_scenes(photo_root)
        assert_equal([item["scene"] for item in photos], ["scene_new", "scene_old"], "photo scenes should be newest first")
        assert_equal(photos[0]["image_count"], "2", "photo scene image count changed")

        write_file(scene_root / "scene_a" / "images" / "frame.jpg", b"frame", 1_700_000_001)
        write_file(scene_root / "scene_a" / "cloud.ply", b"ply", 1_700_000_001)
        write_file(scene_root / "scene_a" / "transforms.json", b"{}", 1_700_000_001)
        write_file(scene_root / "scene_b" / "images" / "frame.jpg", b"frame", 1_700_000_002)
        set_mtime(scene_root / "scene_a", 1_700_000_001)
        set_mtime(scene_root / "scene_b", 1_700_000_002)
        (scene_root / "LATEST_SCENE.txt").write_text("scene_a\n", encoding="utf-8")

        datasets = discover_scene_datasets(scene_root)
        assert_equal([item["scene"] for item in datasets], ["scene_b", "scene_a"], "datasets should be newest first")
        scene_a = next(item for item in datasets if item["scene"] == "scene_a")
        assert_equal(scene_a["image_count"], "1", "dataset image count changed")
        assert_equal(scene_a["pointcloud_count"], "1", "dataset pointcloud count changed")
        assert_equal(scene_a["has_transforms"], "True", "dataset transforms flag changed")
        assert_equal(read_latest_scene(scene_root), "scene_a", "latest scene marker changed")
    print("[OK] asset inventory photo scenes and datasets")


def test_summary_payload_builders() -> None:
    uploads = build_uploads_summary_payload(
        watch_dir=Path("/tmp/watch"),
        queue_enabled=True,
        queue_root=Path("/tmp/queue"),
        queue_summary={"count": 2, "queued": 1},
        archive_dir=Path("/tmp/archive"),
        cleanup_mode="archive",
        archive_keep="5",
        uploaded_count=3,
        items=[{"name": "frame.jpg", "mtime": "2026-06-14 12:00:00"}],
        jobs=[{"id": "wx_01"}],
        archives=[{"name": "archive_01"}],
        queue_archives=[{"name": "queue_archive_01"}],
    )
    assert_equal(uploads["watch_dir"], str(Path("/tmp/watch")), "upload summary watch dir changed")
    assert_equal(uploads["queue"], {"count": 2, "queued": 1}, "upload summary queue changed")
    assert_equal(uploads["latest_mtime"], "2026-06-14 12:00:00", "upload latest mtime changed")
    assert_equal(uploads["count"], 3, "upload count changed")
    assert_equal(uploads["jobs"], [{"id": "wx_01"}], "upload jobs changed")

    legacy_uploads = build_uploads_summary_payload(
        watch_dir=Path("/tmp/watch"),
        queue_enabled=False,
        queue_root=Path("/tmp/queue"),
        queue_summary={"count": 99, "queued": 99},
        archive_dir=Path("/tmp/archive"),
        cleanup_mode="delete",
        archive_keep="1",
        uploaded_count=0,
        items=[],
        jobs=[],
        archives=[],
        queue_archives=[],
    )
    assert_equal(legacy_uploads["queue"], {"count": 0, "queued": 0}, "legacy upload queue should be hidden")
    assert_equal(legacy_uploads["latest_mtime"], None, "empty latest mtime changed")

    scenes = build_scenes_summary_payload(
        latest_scene="scene_a",
        datasets=[{"scene": "scene_a"}, {"scene": "scene_b"}],
        photo_scenes=[{"scene": "scene_a"}],
        pointclouds=[{"name": "scene_a.ply"}],
    )
    assert_equal(scenes["latest_scene"], "scene_a", "scene latest marker changed")
    assert_equal(scenes["dataset_count"], 2, "dataset count changed")
    assert_equal(scenes["photo_scene_count"], 1, "photo scene count changed")
    assert_equal(scenes["pointcloud_count"], 1, "pointcloud count changed")
    print("[OK] asset inventory summary payloads")


def main() -> None:
    test_uploaded_images()
    test_archive_dirs()
    test_photo_scenes_and_datasets()
    test_summary_payload_builders()
    print("[OK] asset inventory checks passed")


if __name__ == "__main__":
    main()
