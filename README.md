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
| `spleen_ct_segmentation` | untested | canonical example, first target |
| `wholeBody_ct_segmentation` | untested | 104 structures (TotalSegmentator-trained) |

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
