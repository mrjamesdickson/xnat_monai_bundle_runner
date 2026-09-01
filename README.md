# xnat_monai_bundle_runner

Run any [MONAI Model Zoo](https://monai.io/model-zoo.html) bundle against XNAT data
via the [Container Service](https://wiki.xnat.org/container-service/). One image,
one command definition — the bundle name is just an input, so every Model Zoo bundle
becomes launchable from XNAT without writing a new command.

Not to be confused with MONAI **Label** (interactive annotation server — see
`xnat_monailabel_plugin`). This is batch inference: launch on a scan or session,
get segmentation/prediction files back as an XNAT resource.

## How it works

1. The Container Service mounts the scan/session NIfTI resource read-only at `/input`.
2. The container downloads the requested bundle (`monai.bundle download`) and runs
   its inference config with `dataset_dir=/input`, `output_dir=/output`.
3. The CS output handler uploads `/output` as a `MONAI` resource on the launch target.

```
XNAT scan (NIFTI) ──► monai-bundle-runner ──► MONAI resource (masks/predictions)
                        bundle-name=spleen_ct_segmentation
```

## Quick start

```bash
# Build
docker build -t xnatworks/monai-bundle-runner:latest .

# Local smoke test (no XNAT needed)
docker run --rm --gpus all \
  -v /path/to/nifti:/input:ro -v /tmp/out:/output \
  -e BUNDLE_NAME=spleen_ct_segmentation \
  xnatworks/monai-bundle-runner:latest

# Install the command in XNAT (as admin)
curl -u admin -X POST "https://your-xnat/xapi/commands" \
  -H 'Content-Type: application/json' -d @commands/monai-bundle-runner.json
```

Then enable the command site-wide and per-project, and launch from a scan's
Run Containers menu with the bundle name of your choice.

## Volumetrics report

Every run also measures the masks it produced and writes three files into the same
`MONAI` resource:

| File | Contents |
|---|---|
| `report.html` | Self-contained report: total volume, structure count, and a per-structure table with proportional bars (light/dark mode, no external assets) |
| `volumes.json` | Machine-readable volumes plus voxel size, matrix, and voxel counts |
| `volumes.csv` | Flat rows for spreadsheets and cross-session aggregation |
| `labels.txt` | ITK-SNAP label description file — names and colours every structure in the mask |
| `labels.ctbl` | 3D Slicer color table, same indices and colours |

The two label files exist so a mask is self-describing when it leaves XNAT: load the
segmentation in ITK-SNAP or Slicer, load the label file beside it, and the structures
arrive named and consistently coloured instead of as bare integers. Colours are a
deterministic golden-angle rotation on the label index — stable across runs and
subjects — and the HTML report shows the same colour as a chip next to each structure,
so the report reads as a legend for whatever viewer you open the mask in. Labels the
bundle declares but that are absent from this particular mask are still listed, which
keeps the colour map identical across a cohort.

Volumes come from voxel counts multiplied by the image's own spacing. Structure
names are read from the bundle's `metadata.json` `channel_def` when it declares
them (so the spleen bundle reports "spleen", not "label 1"), falling back to label
numbers otherwise. Report generation never fails a run — a bundle whose output
isn't a label map still completes with its segmentation intact.

## Inputs

| Input | Required | Description |
|---|---|---|
| `bundle-name` | yes | Model Zoo bundle name, e.g. `spleen_ct_segmentation`, `wholeBody_ct_segmentation` |
| `bundle-version` | no | Pin a bundle version; latest if empty |
| `extra-args` | no | Extra `monai.bundle run` overrides for bundles with non-standard config keys |

## Tested bundles

Bundles differ in their inference config keys; most modern ones accept
`dataset_dir`/`output_dir` overrides, some need `extra-args`. Record what works here:

| Bundle | Works | Notes |
|---|---|---|
| `spleen_ct_segmentation` | ✅ 2026-08-31 | Verified end-to-end on a real abdomen/pelvis CT (CPTAC C3L-00189): segmented 302.9 mL as one connected label — anatomically plausible spleen. RTX 4090, ~8s inference. |
| `wholeBody_ct_segmentation` | untested | 104 structures (TotalSegmentator-trained) |

### Input staging

Bundles glob a path under `dataset_dir` (typically `imagesTs/*.nii.gz`), but an XNAT
resource is a flat directory that may hold uncompressed `.nii` plus JSON sidecars.
The runner reads the glob out of the bundle's inference config and stages inputs to
match it — creating the expected subdirectory, gzip/gunzip-ing to the expected
extension, and skipping non-image files. Without this the dataloader silently comes
up empty and the bundle "succeeds" with no output.

### Wrapper contexts

| Wrapper | Launch from | Input it segments |
|---|---|---|
| `monai-bundle-scan` | a scan | that scan's `NIFTI` resource |
| `monai-bundle-session` | a session | a scan you pick from the session (any scan with a `NIFTI` resource) |

The session wrapper reaches **down to the scans** rather than looking for a
session-level `NIFTI` resource. Session-level NIfTI is rare — most XNAT data has it
on the scan — and a session-scoped input that cannot resolve makes the launch form
fail with `HTTP 400: required fields cannot be resolved`, which is how the UI reports
it. Output lands on the chosen scan either way, next to the data it came from.

Run `tests/launch_form_check.sh <host> <user> <project> <session> [scan]` after any
wrapper change: it calls the same launch-form endpoint the "Run Containers" menu
uses, so a wrapper that would fail to open in the UI fails there first.

### Launching via REST

The launch endpoint takes the numeric wrapper ID, not the wrapper name:

```bash
WID=$(curl -su admin "https://your-xnat/xapi/commands/<cmd-id>" | jq -r '.xnat[] | select(.name=="monai-bundle-scan").id')
curl -su admin -X POST "https://your-xnat/xapi/projects/<proj>/wrappers/$WID/root/scan/launch" \
  -H 'Content-Type: application/json' \
  -d '{"scan":"/experiments/<session>/scans/<scan>","bundle-name":"spleen_ct_segmentation"}'
```

For the session wrapper, either omit `scan` and let resolution pick the only
matching one, or pass the **`/archive`-prefixed** URI the launch form reports
(`/archive/experiments/<session>/scans/<scan>`). A bare `/experiments/...` URI for a
*derived* input fails resolution, and because staging happens after the endpoint has
already returned `HTTP 200` with a workflow id, the launch looks successful while no
container is ever created — the evidence is only in
`containers-services-commandresolution.log`.

## Licensing

This repo: Apache 2.0. **Bundle weights are licensed per-bundle** — the container
downloads them at runtime from the Model Zoo under the deploying site's
responsibility; nothing is redistributed here. Check each bundle's LICENSE and
`docs/data_license.txt` before use. Not a medical device; research/decision
support only.

## Requirements

- Container Service 3.6.0+ (XNAT 1.9.x)
- GPU host with nvidia runtime configured on the Docker server (`runtime: nvidia`
  is set in the command); CPU fallback works but is slow
- Outbound network access from the container to download bundles (or pre-bake
  bundles into a derived image for air-gapped sites)
