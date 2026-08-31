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
