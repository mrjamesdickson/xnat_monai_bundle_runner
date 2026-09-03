# Should the runner be a custom image? — the setup/wrapup provisioning pattern

Recorded 2026-09-03. **Decision pending** (James: "I can't decide right now"). Nothing in
this repo has been changed on the strength of it.

## The question

Today this repo ships a custom image, `xnatworks/monai-bundle-runner`, that is stock
PyTorch plus a pip install of MONAI plus 25 KB of our own scripts. James's position:

> I like having official images with xnatworks stuff either in a setup container or a
> wrapup container. People trust the official image. We are just provisioning.

That is the pattern every other card in the catalog already follows — TotalSegmentator,
MOOSE and MuscleMap all run **unmodified upstream images** with `seg-wrapup` behind them.
The bundle runner is the only card that builds its own image, so it is the only one where
the question arises.

## The enabling fact, verified in the Container Service source

`CommandResolutionServiceImpl` (CS 3.7.3, lines ~471-491, local clone
`development/container-service` at `8590cb6c`) populates setup and wrapup commands
**identically**, and both get two things from the parent command:

```java
// Populate setup & wrap-up commands with environment variables from parent command
for (ResolvedCommand setup : resolvedSetupCommands) {
    populatedSetupCommands.add(
        setup.toBuilder()
             .addEnvironmentVariables(resolvedEnvironmentVariables)
             .commandLine(resolveCommandLine(resolvedCommandLineValuesByReplacementKey, setup.commandLine()))
             ...
```

1. **The parent's resolved environment variables.** A card that sets `BUNDLE_NAME` reaches
   its setup container with that value.
2. **Replacement-key substitution in the setup command's own command line.** A setup
   command's `command-line` may contain the parent's replacement keys and they are
   substituted before it runs.

Point 2 is what makes this design possible: **one generic setup image can be
parameterised per card**, so we do not need a setup command per bundle.

Two related facts from the same read:

- `ResolvedCommand.fromSpecialCommandType` never sets `overrideEntrypoint`, so a setup or
  wrapup container always runs with its image entrypoint intact. A chained command line
  needs its own `sh -c '...'`.
- `prepareToLaunch` adds only the *default* environment (`XNAT_USER`, `XNAT_PASS`,
  `XNAT_HOST`, workflow and event ids). The parent's variables arrive by the loop above,
  not there.

## The shape it would take

| Stage | Image | Does |
|---|---|---|
| setup | ours, thin | DICOM to NIfTI; fetch the bundle; stage inputs to the layout the bundle's inference config globs for |
| model | **`projectmonai/monai`, untouched** | `python -m monai.bundle run --config_file ... --bundle_root ... --dataset_dir ... --output_dir /output` |
| wrapup | ours (`xnatworks/seg-wrapup`) | report, label tables, DICOM SEG, OHIF ROI collection |

Neither of our containers touches the model or its weights, which is the part users
actually want unmodified. The custom runner image disappears; `run_bundle.sh` moves into
the setup image and `make_report.py` is deleted outright, because seg-wrapup has done the
report since 0.2.0.

## What has to be decided first

**Only one setup command can attach to an input** (`via-setup-command` is a single value),
so DICOM conversion and bundle fetching must live in the *same* image. That decides what
that image contains, and the bundle fetch is the open question:

| Option | Cost |
|---|---|
| Find the real bundle hosting URL and fetch with `curl` | Thin setup image (dcm2niix + curl + unzip). **Unverified** — two plausible URLs both returned 404, see below |
| Base the setup image on the official MONAI image and add a DICOM converter | Model image stays stock, but the setup image is ~10 GB |
| Pre-fetch bundles into a host cache volume; setup only stages | Thin image, but adds host provisioning and breaks self-containment |

Sizes for reference:

| Image | Size |
|---|---|
| `projectmonai/monai:1.6.0` | 9.96 GB |
| `xnatworks/monai-bundle-runner:0.1.0` (current) | 7.75 GB |

**Not established:** a direct HTTP download route for a bundle. `monai.bundle download`
defaults to source `monaihosting` (confirmed in the 1.6.0 source, see
[MONAI_1_6.md](MONAI_1_6.md)), but the underlying URL was not identified. Two guesses were
tried on 2026-09-03 and both 404'd:

```
https://api.ngc.nvidia.com/v2/models/nvidia/monaihosting/spleen_ct_segmentation/versions/0.6.1/files/spleen_ct_segmentation_v0.6.1.zip
https://github.com/Project-MONAI/model-zoo/releases/download/hosting_storage_v1/spleen_ct_segmentation_v0.6.1.zip
```

Read `monai/bundle/scripts.py` in the 1.6.0 tag for the real pattern before choosing the
`curl` option.

## Status quo, for the record

The two bundle cards published on 2026-09-03 (`monai-wholebody` 1.0.0 and `monai-spleen`
1.0.0) run on the current custom image at the pinned tag `0.1.0`, which was pushed to
Docker Hub that day so the catalog gate could resolve a digest. Both were verified live on
demo02: 70 structures on a chest CTPA and the spleen at 303 mL on an abdominal study, each
with a DICOM SEG and a registered ROI collection. Rebuilding them on the official image is
a change of provisioning, not of behaviour.

## Also pending

The knowledge hub's Container Service note (hub PR #69) says the setup command line "runs
as-is". That is true about the entrypoint but omits the replacement-key substitution above,
which is the basis of this whole design. The note should gain that fact — held back for now
because James asked that this material stay in the project rather than going to the hub.
