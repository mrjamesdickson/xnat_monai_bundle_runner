#!/usr/bin/env python
"""Compute per-structure volumes from segmentation masks and write an HTML report.

Reads every NIfTI in the output directory, treats non-zero integer values as
structure labels, and converts voxel counts to millilitres using the image's own
voxel spacing. Structure names come from the bundle's metadata.json when it
declares them; otherwise labels are reported by number.

Writes volumes.json (machine-readable), volumes.csv, and report.html alongside
the masks, so all three land in the XNAT resource with the segmentation.
"""
from __future__ import annotations

import csv
import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import nibabel as nib
import numpy as np

# Single-series magnitude chart: one hue, light and dark steps validated against
# their own surfaces (dataviz reference palette, categorical slot 1).
CSS = """
:root { color-scheme: light dark; }
.viz-root {
  --surface-1: #fcfcfb; --surface-2: #f2f2f0; --border: #dededa;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #767470;
  --series-1: #2a78d6;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz-root {
    --surface-1: #1a1a19; --surface-2: #242423; --border: #3a3a38;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #96958c;
    --series-1: #3987e5;
  }
}
body { margin: 0; background: var(--surface-1); }
.viz-root {
  background: var(--surface-1); color: var(--text-primary);
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  padding: 32px; max-width: 900px; margin: 0 auto;
}
h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px; }
.subtitle { color: var(--text-secondary); font-size: 13px; margin: 0 0 24px; }
.tiles { display: flex; gap: 32px; margin: 0 0 28px; flex-wrap: wrap; }
.tile-value { font-size: 28px; font-weight: 600; letter-spacing: -0.02em; }
.tile-label { color: var(--text-secondary); font-size: 12px; text-transform: uppercase;
              letter-spacing: 0.04em; margin-top: 2px; }
table { border-collapse: collapse; width: 100%; }
th { text-align: left; font-size: 12px; font-weight: 600; color: var(--text-secondary);
     text-transform: uppercase; letter-spacing: 0.04em;
     padding: 0 12px 8px 0; border-bottom: 1px solid var(--border); }
th.num, td.num { text-align: right; }
td { padding: 10px 12px 10px 0; border-bottom: 1px solid var(--border);
     font-variant-numeric: tabular-nums; }
td.name { font-weight: 500; }
.bar-cell { width: 42%; padding-right: 0; }
.bar-track { background: var(--surface-2); border-radius: 2px; height: 14px; width: 100%; }
.bar-fill { background: var(--series-1); height: 14px;
            border-radius: 0 4px 4px 0; min-width: 2px; }
.file-heading { font-size: 13px; font-weight: 600; color: var(--text-secondary);
                margin: 28px 0 10px; word-break: break-all; }
footer { margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--border);
         color: var(--text-muted); font-size: 12px; }
footer p { margin: 4px 0; }
.empty { color: var(--text-muted); font-style: italic; }
"""


def load_label_names(bundle_root: Path) -> dict[int, str]:
    """Read structure names from a bundle's metadata.json channel_def, if present."""
    meta_path = bundle_root / "configs" / "metadata.json"
    if not meta_path.is_file():
        return {}
    try:
        with meta_path.open() as handle:
            metadata = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"WARNING: could not read {meta_path}: {error}", file=sys.stderr)
        return {}

    outputs = metadata.get("network_data_format", {}).get("outputs", {})
    for output_spec in outputs.values():
        channel_def = output_spec.get("channel_def")
        if not isinstance(channel_def, dict):
            continue
        names: dict[int, str] = {}
        for key, value in channel_def.items():
            try:
                names[int(key)] = str(value)
            except (TypeError, ValueError):
                continue
        if names:
            return names
    return {}


def measure_mask(mask_path: Path, label_names: dict[int, str]) -> dict:
    """Return per-label volumes for one segmentation file."""
    image = nib.load(str(mask_path))
    data = np.asanyarray(image.dataobj)
    if data.ndim == 4 and data.shape[-1] == 1:
        data = data[..., 0]

    zooms = image.header.get_zooms()[:3]
    voxel_mm3 = float(np.prod(zooms))
    voxel_ml = voxel_mm3 / 1000.0

    structures = []
    for label in np.unique(data):
        label = int(label)
        if label == 0:
            continue
        voxels = int((data == label).sum())
        if voxels == 0:
            continue
        name = label_names.get(label, f"label {label}")
        if name.lower() == "background":
            continue
        structures.append(
            {
                "label": label,
                "name": name,
                "voxels": voxels,
                "volume_ml": round(voxels * voxel_ml, 2),
            }
        )
    structures.sort(key=lambda item: item["volume_ml"], reverse=True)

    return {
        "file": mask_path.name,
        "shape": [int(dimension) for dimension in data.shape],
        "voxel_size_mm": [round(float(zoom), 4) for zoom in zooms],
        "voxel_volume_mm3": round(voxel_mm3, 4),
        "structures": structures,
        "total_volume_ml": round(sum(item["volume_ml"] for item in structures), 2),
    }


def render_html(report: dict) -> str:
    """Render the volumetrics report as a self-contained HTML document."""
    bundle = html.escape(report["bundle"])
    context_bits = [f"Bundle <strong>{bundle}</strong>"]
    if report.get("session"):
        context_bits.append(f"session <strong>{html.escape(report['session'])}</strong>")
    if report.get("scan"):
        context_bits.append(f"scan <strong>{html.escape(report['scan'])}</strong>")
    context_bits.append(f"generated {html.escape(report['generated'])}")

    total_volume = sum(result["total_volume_ml"] for result in report["results"])
    total_structures = sum(len(result["structures"]) for result in report["results"])

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Segmentation volumes</title>",
        f"<style>{CSS}</style></head><body>",
        '<div class="viz-root">',
        "<h1>Segmentation volumes</h1>",
        f'<p class="subtitle">{" &middot; ".join(context_bits)}</p>',
        '<div class="tiles">',
        f'<div><div class="tile-value">{total_volume:,.1f} mL</div>'
        '<div class="tile-label">Total segmented volume</div></div>',
        f'<div><div class="tile-value">{total_structures}</div>'
        '<div class="tile-label">Structures found</div></div>',
        "</div>",
    ]

    show_headings = len(report["results"]) > 1
    for result in report["results"]:
        if show_headings:
            parts.append(f'<p class="file-heading">{html.escape(result["file"])}</p>')

        if not result["structures"]:
            parts.append('<p class="empty">No labelled structures in this mask.</p>')
            continue

        largest = max(item["volume_ml"] for item in result["structures"]) or 1.0
        parts.append(
            "<table><thead><tr>"
            "<th>Structure</th><th class='num'>Volume (mL)</th>"
            "<th class='num'>Voxels</th><th class='num'>Share</th>"
            "<th class='bar-cell'></th>"
            "</tr></thead><tbody>"
        )
        for item in result["structures"]:
            share = (
                item["volume_ml"] / result["total_volume_ml"] * 100
                if result["total_volume_ml"]
                else 0.0
            )
            width = max(item["volume_ml"] / largest * 100, 0.5)
            title = html.escape(f"{item['name']}: {item['volume_ml']:,.2f} mL")
            parts.append(
                f"<tr><td class='name'>{html.escape(item['name'])}</td>"
                f"<td class='num'>{item['volume_ml']:,.2f}</td>"
                f"<td class='num'>{item['voxels']:,}</td>"
                f"<td class='num'>{share:.1f}%</td>"
                f"<td class='bar-cell'><div class='bar-track' title='{title}'>"
                f"<div class='bar-fill' style='width:{width:.1f}%'></div></div></td></tr>"
            )
        parts.append("</tbody></table>")

        voxel = " &times; ".join(f"{size:g}" for size in result["voxel_size_mm"])
        parts.append(
            f'<footer><p>Voxel size {voxel} mm &middot; '
            f'matrix {" &times; ".join(str(dimension) for dimension in result["shape"])}</p>'
        )
        parts.append(
            "<p>Volumes are computed from voxel counts and image spacing. "
            "Research and decision support only &mdash; not a medical device, "
            "not for diagnostic use.</p></footer>"
        )

    parts.append("</div></body></html>")
    return "\n".join(parts)


def main() -> int:
    output_dir = Path(os.environ.get("OUTPUT_DIR", "/output"))
    bundle_root = Path(os.environ.get("BUNDLE_ROOT", "/bundles"))
    bundle_name = os.environ.get("BUNDLE_NAME", "unknown")

    mask_paths = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.name.endswith((".nii", ".nii.gz"))
    )
    if not mask_paths:
        print("WARNING: no NIfTI masks found to measure; skipping report", file=sys.stderr)
        return 0

    label_names = load_label_names(bundle_root)
    results = []
    for mask_path in mask_paths:
        try:
            results.append(measure_mask(mask_path, label_names))
        except Exception as error:  # noqa: BLE001 - report and continue over remaining masks
            print(f"ERROR: failed to measure {mask_path}: {error}", file=sys.stderr)

    if not results:
        print("ERROR: no masks could be measured", file=sys.stderr)
        return 1

    report = {
        "bundle": bundle_name,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "session": os.environ.get("SESSION_LABEL", ""),
        "scan": os.environ.get("SCAN_ID", ""),
        "results": results,
    }

    (output_dir / "volumes.json").write_text(json.dumps(report, indent=2))

    with (output_dir / "volumes.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "label", "structure", "voxels", "volume_ml"])
        for result in results:
            for item in result["structures"]:
                writer.writerow(
                    [result["file"], item["label"], item["name"], item["voxels"], item["volume_ml"]]
                )

    (output_dir / "report.html").write_text(render_html(report))

    for result in results:
        for item in result["structures"]:
            print(f"  {item['name']}: {item['volume_ml']:,.2f} mL ({item['voxels']:,} voxels)")
    print(f"wrote report.html, volumes.json, volumes.csv to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
