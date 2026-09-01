"""Tests for the volumetrics report generator.

Run: python -m pytest tests/test_make_report.py
Requires nibabel + numpy (present in the runner image).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import make_report  # noqa: E402


def write_mask(path, array, voxel_size=(1.0, 1.0, 1.0)):
    affine = np.diag([*voxel_size, 1.0])
    nib.save(nib.Nifti1Image(array.astype(np.uint8), affine), str(path))


def test_measure_mask_converts_voxels_to_millilitres(tmp_path):
    # 10x10x10 cube of label 1 at 2mm isotropic = 1000 voxels * 8 mm3 = 8000 mm3 = 8 mL
    data = np.zeros((20, 20, 20), dtype=np.uint8)
    data[:10, :10, :10] = 1
    mask = tmp_path / "cube.nii.gz"
    write_mask(mask, data, voxel_size=(2.0, 2.0, 2.0))

    result = make_report.measure_mask(mask, {1: "spleen"})

    assert len(result["structures"]) == 1
    structure = result["structures"][0]
    assert structure["name"] == "spleen"
    assert structure["voxels"] == 1000
    assert structure["volume_ml"] == pytest.approx(8.0)
    assert result["total_volume_ml"] == pytest.approx(8.0)


def test_measure_mask_reports_each_label_and_sorts_by_volume(tmp_path):
    data = np.zeros((10, 10, 10), dtype=np.uint8)
    data[:2, :, :] = 1      # 200 voxels
    data[2:8, :, :] = 2     # 600 voxels
    mask = tmp_path / "multi.nii.gz"
    write_mask(mask, data)

    result = make_report.measure_mask(mask, {1: "liver", 2: "lung"})

    assert [item["name"] for item in result["structures"]] == ["lung", "liver"]
    assert [item["voxels"] for item in result["structures"]] == [600, 200]
    assert result["total_volume_ml"] == pytest.approx(0.8)


def test_background_and_unnamed_labels(tmp_path):
    data = np.zeros((10, 10, 10), dtype=np.uint8)
    data[:5, :, :] = 3
    mask = tmp_path / "unnamed.nii.gz"
    write_mask(mask, data)

    # Label 0 is never counted; an unmapped label falls back to its number.
    result = make_report.measure_mask(mask, {0: "background"})

    assert len(result["structures"]) == 1
    assert result["structures"][0]["name"] == "label 3"


def test_label_names_read_from_bundle_metadata(tmp_path):
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "metadata.json").write_text(
        json.dumps(
            {
                "network_data_format": {
                    "outputs": {"pred": {"channel_def": {"0": "background", "1": "spleen"}}}
                }
            }
        )
    )

    assert make_report.load_label_names(tmp_path) == {0: "background", 1: "spleen"}


def test_missing_metadata_returns_empty_names(tmp_path):
    assert make_report.load_label_names(tmp_path) == {}


def test_end_to_end_writes_all_three_artifacts(tmp_path):
    data = np.zeros((10, 10, 10), dtype=np.uint8)
    data[:5, :, :] = 1
    write_mask(tmp_path / "seg.nii.gz", data)

    env = {**os.environ, "OUTPUT_DIR": str(tmp_path), "BUNDLE_ROOT": str(tmp_path),
           "BUNDLE_NAME": "test_bundle"}
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "make_report.py")],
        env=env, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr

    report = json.loads((tmp_path / "volumes.json").read_text())
    assert report["bundle"] == "test_bundle"
    assert report["results"][0]["structures"][0]["voxels"] == 500

    csv_text = (tmp_path / "volumes.csv").read_text()
    assert "file,label,structure,voxels,volume_ml" in csv_text

    report_html = (tmp_path / "report.html").read_text()
    assert "Segmentation volumes" in report_html
    assert "bar-fill" in report_html
    # Control assertion: the measured value actually reaches the page.
    assert "0.50" in report_html


def test_multiple_masks_share_one_disclaimer_and_are_all_listed(tmp_path):
    for index, name in enumerate(["a", "b"], start=1):
        data = np.zeros((6, 6, 6), dtype=np.uint8)
        data[:index] = 1
        write_mask(tmp_path / f"{name}.nii.gz", data)

    env = {**os.environ, "OUTPUT_DIR": str(tmp_path), "BUNDLE_ROOT": str(tmp_path),
           "BUNDLE_NAME": "multi"}
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "make_report.py")],
        env=env, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr

    report_html = (tmp_path / "report.html").read_text()
    assert report_html.count("not a medical device") == 1
    assert report_html.count("<footer>") == 1
    # Both masks are still reported, each with its own per-file caption.
    assert "a.nii.gz" in report_html and "b.nii.gz" in report_html
    assert report_html.count('class="caption"') == 2


def test_itksnap_label_file_format(tmp_path):
    text = make_report.itksnap_label_file({1: "spleen", 5: "liver"})
    lines = [line for line in text.splitlines() if not line.startswith("#")]

    # Index 0 is the reserved transparent entry ITK-SNAP requires.
    assert lines[0].split() == ["0", "0", "0", "0", "0", "0", "0", '"Clear', 'Label"']

    # Each data row is IDX R G B A VIS MSH "name" with 8 whitespace-split fields.
    spleen = lines[1].split()
    assert spleen[0] == "1"
    assert all(0 <= int(channel) <= 255 for channel in spleen[1:4])
    assert spleen[4:7] == ["1", "1", "1"]
    assert spleen[7] == '"spleen"'
    assert lines[2].split()[0] == "5"


def test_slicer_ctbl_uses_the_same_colors_as_itksnap(tmp_path):
    labels = {1: "spleen", 2: "liver"}
    snap = make_report.itksnap_label_file(labels)
    ctbl = make_report.slicer_color_table(labels)

    for label in labels:
        red, green, blue = make_report.label_color(label)
        assert f"{red:5d} {green:4d} {blue:4d}" in snap
        assert f"{label} {labels[label]} {red} {green} {blue} 255" in ctbl


def test_label_colors_are_deterministic_and_distinct():
    first = [make_report.label_color(index) for index in range(1, 9)]
    second = [make_report.label_color(index) for index in range(1, 9)]

    assert first == second, "colors must be stable across runs"
    assert len(set(first)) == len(first), "adjacent labels must not share a color"


def test_collect_labels_keeps_declared_and_adds_observed():
    declared = {0: "background", 1: "spleen"}
    results = [{"structures": [{"label": 7, "name": "label 7"}]}]

    labels = make_report.collect_labels(declared, results)

    assert labels == {1: "spleen", 7: "label 7"}
    assert 0 not in labels, "background must never become a visible label"


def test_label_files_written_and_report_chip_matches(tmp_path):
    data = np.zeros((8, 8, 8), dtype=np.uint8)
    data[:4] = 1
    write_mask(tmp_path / "seg.nii.gz", data)
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "metadata.json").write_text(
        json.dumps(
            {"network_data_format": {"outputs": {"pred": {"channel_def": {"0": "background",
                                                                          "1": "spleen"}}}}}
        )
    )

    env = {**os.environ, "OUTPUT_DIR": str(tmp_path), "BUNDLE_ROOT": str(tmp_path),
           "BUNDLE_NAME": "spleen_ct_segmentation"}
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "make_report.py")],
        env=env, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr

    assert '"spleen"' in (tmp_path / "labels.txt").read_text()
    assert "1 spleen" in (tmp_path / "labels.ctbl").read_text()

    # The report's colour chip must match the viewer colour for the same label.
    red, green, blue = make_report.label_color(1)
    assert f"rgb({red},{green},{blue})" in (tmp_path / "report.html").read_text()


def test_report_survives_a_mask_it_cannot_measure(tmp_path):
    (tmp_path / "broken.nii.gz").write_bytes(b"not a nifti")
    data = np.zeros((4, 4, 4), dtype=np.uint8)
    data[:2] = 1
    write_mask(tmp_path / "good.nii.gz", data)

    env = {**os.environ, "OUTPUT_DIR": str(tmp_path), "BUNDLE_ROOT": str(tmp_path),
           "BUNDLE_NAME": "partial"}
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "make_report.py")],
        env=env, capture_output=True, text=True,
    )

    assert completed.returncode == 0
    assert "failed to measure" in completed.stderr
    report = json.loads((tmp_path / "volumes.json").read_text())
    assert len(report["results"]) == 1
