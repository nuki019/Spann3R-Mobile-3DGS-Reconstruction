"""Offline checks for point cloud discovery and download selection helpers."""

from __future__ import annotations

import os
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.pointcloud_index import (  # pylint: disable=wrong-import-position
    build_pointclouds_summary_payload,
    build_zip_archive_name,
    clear_pointcloud_files,
    discover_pointclouds,
    filter_pointclouds_by_processed,
    find_scene_gaussian_files,
    index_by_id,
    infer_pointcloud_variant,
    is_processed_pointcloud,
    normalize_prefer,
    parse_pointcloud_roots,
    pick_preferred_pointcloud,
    select_latest_pointcloud,
    select_scene_pointcloud,
    select_zip_pointclouds,
    summarize_pointclouds,
    under_allowed_roots,
    write_pointcloud_zip,
)


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def write_fake_ply(path: Path, payload: bytes, mtime: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    os.utime(path, (mtime, mtime))
    return path


def build_fixture(tmp_root: Path) -> tuple[list[Path], dict[str, Path]]:
    gs_root = tmp_root / "gs_train"
    spann3r_root = tmp_root / "Spann3R" / "output" / "demo"
    outside_root = tmp_root / "outside"
    base_mtime = 1_700_000_000
    files = {
        "old_raw": write_fake_ply(
            gs_root / "scenes" / "scene_old" / "scene_old_raw.ply",
            b"raw-old",
            base_mtime + 10,
        ),
        "old_train": write_fake_ply(
            gs_root / "scenes" / "scene_old" / "scene_old_init.ply",
            b"train-old",
            base_mtime + 20,
        ),
        "new_raw_gaussian": write_fake_ply(
            gs_root / "outputs" / "scene_new" / "splatfacto" / "point_cloud.ply",
            b"gaussian-raw",
            base_mtime + 30,
        ),
        "new_clipped": write_fake_ply(
            gs_root / "scenes" / "scene_new" / "scene_new_gaussian_clipped.ply",
            b"gaussian-clipped",
            base_mtime + 40,
        ),
        "new_downsampled": write_fake_ply(
            spann3r_root / "scene_new" / "scene_new_downsampled.ply",
            b"downsampled",
            base_mtime + 50,
        ),
        "outside": write_fake_ply(
            outside_root / "outside_downsampled.ply",
            b"outside",
            base_mtime + 60,
        ),
    }
    return [gs_root, spann3r_root], files


def check_variant_inference() -> None:
    cases = {
        "scene_gaussian_clipped.ply": "gaussian",
        "scene_downsampled.ply": "downsampled",
        "scene_raw.ply": "raw",
        "scene_init.ply": "train",
        "mesh.ply": "other",
    }
    for name, expected in cases.items():
        expect(infer_pointcloud_variant(Path(name)) == expected, f"variant mismatch for {name}")
    expect(
        infer_pointcloud_variant(Path("outputs/scene/splatfacto/point_cloud.ply")) == "gaussian",
        "splatfacto point_cloud must be gaussian",
    )


def check_discovery_and_selection(roots: list[Path], files: dict[str, Path]) -> list[dict[str, str]]:
    items = discover_pointclouds(roots)
    expect(len(items) == 5, "discovery should ignore files outside configured roots")
    expect(items[0]["name"] == "scene_new_downsampled.ply", "items should be sorted newest first")
    expect(all(item.get("download_url", "").startswith("/download/") for item in items), "missing URLs")
    expect({item["scene"] for item in items} == {"scene_new", "scene_old"}, "scene inference failed")

    expect(under_allowed_roots(files["new_clipped"], roots), "allowed file rejected")
    expect(not under_allowed_roots(files["outside"], roots), "outside file accepted")

    latest_gaussian = pick_preferred_pointcloud(
        items,
        prefer="gaussian",
        strict=True,
        latest_scene="scene_new",
    )
    expect(latest_gaussian is not None, "strict gaussian selection failed")
    expect(latest_gaussian["name"] == "scene_new_gaussian_clipped.ply", "wrong gaussian selected")

    old_scene = [item for item in items if item["scene"] == "scene_old"]
    fallback = pick_preferred_pointcloud(old_scene, prefer="gaussian", strict=False)
    expect(fallback is not None and fallback["variant"] == "train", "fallback order changed")

    strict_missing = pick_preferred_pointcloud(old_scene, prefer="gaussian", strict=True)
    expect(strict_missing is None, "strict selection should not fallback when variant is missing")
    return items


def check_processed_summary_and_index(items: list[dict[str, str]]) -> None:
    processed = filter_pointclouds_by_processed(items, True)
    raw = filter_pointclouds_by_processed(items, False)
    expect({item["variant"] for item in processed} >= {"downsampled", "train"}, "processed filter failed")
    expect(any(item["name"] == "scene_new_gaussian_clipped.ply" for item in processed), "clipped missing")
    expect(all(not is_processed_pointcloud(item) for item in raw), "raw filter leaked processed files")

    summary = summarize_pointclouds(items)
    expect(summary["count"] == len(items), "summary count mismatch")
    expect(summary["scenes"]["scene_new"] == 3, "summary scene count mismatch")
    expect(summary["latest"]["name"] == items[0]["name"], "summary latest mismatch")

    mapping = index_by_id(items)
    expect(set(mapping) == {item["id"] for item in items}, "id index mismatch")

    payload = build_pointclouds_summary_payload(items, limit=2)
    expect(payload["summary"] == summary, "pointcloud summary payload changed")
    expect(len(payload["items"]) == 2, "pointcloud summary limit changed")


def check_download_selection_helpers(items: list[dict[str, str]]) -> None:
    expect(normalize_prefer("") == "gaussian", "empty prefer normalization changed")
    expect(normalize_prefer(" Any ") == "any", "prefer normalization should trim and lowercase")

    latest_gaussian = select_latest_pointcloud(items, prefer="gaussian")
    expect(latest_gaussian is not None, "latest gaussian selection failed")
    expect(latest_gaussian["name"] == "scene_new_gaussian_clipped.ply", "latest gaussian changed")

    old_scene = [item for item in items if item["scene"] == "scene_old"]
    expect(select_latest_pointcloud(old_scene, prefer="gaussian") is None, "strict latest should not fallback")
    fallback = select_latest_pointcloud(old_scene, prefer="gaussian", strict=False)
    expect(fallback is not None and fallback["variant"] == "train", "non-strict latest fallback changed")

    scene_downsampled = select_scene_pointcloud(items, "scene_new", prefer="downsampled")
    expect(scene_downsampled is not None and scene_downsampled["variant"] == "downsampled", "scene selection failed")
    expect(select_scene_pointcloud(items, "missing", prefer="any") is None, "missing scene should return none")

    zipped_latest = select_zip_pointclouds(items, variant="gaussian", latest_scene="scene_new")
    expect({item["name"] for item in zipped_latest} == {"point_cloud.ply", "scene_new_gaussian_clipped.ply"}, "zip latest gaussian selection changed")

    zipped_processed = select_zip_pointclouds(items, variant="any", processed=True, latest_scene="scene_new")
    expect(
        {item["name"] for item in zipped_processed}
        == {"scene_new_downsampled.ply", "scene_new_gaussian_clipped.ply"},
        "zip processed latest selection changed",
    )

    wanted_ids = ",".join([items[0]["id"], items[-1]["id"], "missing"])
    zipped_ids = select_zip_pointclouds(items, ids=wanted_ids, variant="raw", processed=True, latest_scene="scene_new")
    expect({item["id"] for item in zipped_ids} == {items[0]["id"], items[-1]["id"]}, "zip ids selection changed")
    expect(build_zip_archive_name("scene_new", " Gaussian ") == "scene_new_gaussian.zip", "zip archive name changed")
    expect(build_zip_archive_name(" scene/new 01 ", "???") == "scene_new_01_any.zip", "zip archive name should be safe")
    expect(build_zip_archive_name("", "") == "pointclouds_any.zip", "default zip archive name changed")
    print("[OK] pointcloud download selection helpers")


def check_scene_gaussian_and_zip(
    roots: list[Path],
    items: list[dict[str, str]],
    files: dict[str, Path],
) -> None:
    gaussian_files = find_scene_gaussian_files("scene_new", items)
    expect(
        gaussian_files == {
            "raw": "point_cloud.ply",
            "clipped": "scene_new_gaussian_clipped.ply",
        },
        "scene gaussian file lookup changed",
    )

    selected = [
        item
        for item in items
        if item["name"] in {"scene_new_downsampled.ply", "scene_new_gaussian_clipped.ply"}
    ]
    selected.append(
        {
            "scene": "scene_new",
            "name": files["outside"].name,
            "path": str(files["outside"]),
        }
    )
    unsafe_name = write_fake_ply(
        files["new_clipped"].parent / "point cloud #1.ply",
        b"unsafe-name",
        1_700_000_099,
    )
    selected.append(
        {
            "scene": "../scene new",
            "name": unsafe_name.name,
            "path": str(unsafe_name),
        }
    )

    with tempfile.TemporaryDirectory() as archive_dir:
        archive_path = Path(archive_dir) / "pointclouds.zip"
        write_pointcloud_zip(selected, roots, archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            names = sorted(archive.namelist())
    expect(
        names == [
            "scene_new_point_cloud__1.ply",
            "scene_new_scene_new_downsampled.ply",
            "scene_new_scene_new_gaussian_clipped.ply",
        ],
        "zip archive contents or safe names changed",
    )


def check_clear_pointcloud_files() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        allowed = root / "allowed"
        outside = root / "outside"
        keep_txt = write_fake_ply(allowed / "keep.txt", b"not-ply", 1_700_000_001)
        delete_a = write_fake_ply(allowed / "scene_a" / "a.ply", b"a", 1_700_000_002)
        outside_ply = write_fake_ply(outside / "outside.ply", b"outside", 1_700_000_004)

        deleted = clear_pointcloud_files([allowed])
        expect(deleted == 1, "clear should only delete allowed .ply files")
        expect(not delete_a.exists(), "allowed lowercase ply should be deleted")
        expect(outside_ply.exists(), "outside ply should be kept")
        expect(keep_txt.exists(), "non-ply file should be kept")
    print("[OK] pointcloud clear model")


def main() -> None:
    check_variant_inference()
    with tempfile.TemporaryDirectory() as tmp_dir:
        roots, files = build_fixture(Path(tmp_dir))
        parsed_roots = parse_pointcloud_roots(",".join(str(root) for root in roots), [])
        expect(parsed_roots == [root.resolve() for root in roots], "root parsing failed")
        items = check_discovery_and_selection(roots, files)
        check_processed_summary_and_index(items)
        check_download_selection_helpers(items)
        check_scene_gaussian_and_zip(roots, items, files)
    check_clear_pointcloud_files()
    print("[OK] pointcloud download model checks passed")


if __name__ == "__main__":
    main()
