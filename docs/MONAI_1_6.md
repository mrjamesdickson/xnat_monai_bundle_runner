# MONAI 1.6.0 — what it changes for this repo

Checked: 2026-09-02. All claims below were read from the sources listed, and every API
name was confirmed against the `1.6.0` git tag rather than the prose summary.

```
sources:
  - https://monai.readthedocs.io/en/stable/whatsnew_1_6.html
  - https://github.com/Project-MONAI/MONAI/releases/tag/1.6.0
  - https://github.com/Project-MONAI/MONAI/blob/1.6.0/setup.cfg
  - https://github.com/Project-MONAI/MONAI/blob/1.6.0/requirements.txt
  - https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/auto3dseg/utils.py
  - https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/utils/misc.py
  - https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/data/image_reader.py
  - https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/bundle/config_parser.py
  - https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/bundle/scripts.py
  - https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/bundle/utils.py
  - https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/losses/__init__.py
  - https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/losses/aucm_loss.py
  - https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/metrics/embedding_collapse.py
  - https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/data/wsi_reader.py
  - https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/transforms/inverse.py
  - https://github.com/advisories/GHSA-rghg-q7wp-9767
  - https://github.com/advisories/GHSA-qxq5-qhx6-94qw
  - https://github.com/Project-MONAI/MONAI/issues/7701
  - https://github.com/Project-MONAI/MONAI/pull/9019
```

## Why this matters here

`Dockerfile` pins `monai[nibabel,itk,tqdm]==1.5.0` on top of
`pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime`. Our entire MONAI surface is two CLI
calls in `run_bundle.sh` — `python -m monai.bundle download` and `python -m monai.bundle
run` — plus whatever the downloaded bundle's own inference config pulls in. `make_report.py`
imports only `nibabel` and `numpy`; it never imports `monai`.

1.6.0 was published 2026-06-11 ([release
tag](https://github.com/Project-MONAI/MONAI/releases/tag/1.6.0)). There are no 1.6.x patch
releases as of the check date — the release list goes `1.5.0`, `1.5.1`, `1.5.2`, `1.6.0`
([releases API](https://github.com/Project-MONAI/MONAI/releases)).

**Moving to 1.6.0 is not a pin bump; it is a base-image change.** 1.5.0 declares
`torch>=2.4.1, <2.7.0`; 1.6.0 declares `torch>=2.8.0`
([1.5.0 setup.cfg](https://github.com/Project-MONAI/MONAI/blob/1.5.0/setup.cfg),
[1.6.0 setup.cfg](https://github.com/Project-MONAI/MONAI/blob/1.6.0/setup.cfg)). Our base
image ships torch 2.4.1, which is outside the 1.6.0 floor and was in fact the *lower bound*
of the 1.5.0 range. The pip install would either fail to resolve or silently drag in a new
torch on top of the CUDA runtime the image was built for.

The counter-argument for moving anyway: our pinned 1.5.0 is inside the affected range of
both open MONAI advisories (see below). Neither is reachable from our code paths as
written, but a vulnerability scanner on the published image will flag them.

Two independent facts to weigh before scheduling this:

- The `monai.bundle` CLI surface we depend on is unchanged. `download()` and `run()` have
  byte-identical signatures in 1.5.0 and 1.6.0
  ([1.6.0 scripts.py](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/bundle/scripts.py)),
  and `DEFAULT_DOWNLOAD_SOURCE` is `"monaihosting"` in both.
- The upstream inverse-transform tracing bug that bit MuscleMap is **not** fixed in 1.6.0.
  See "Not established / not fixed" below.

## The changes

Verified against the 1.6.0 tag. Where the release page and the shipped code disagree, that
is called out.

| Change | Exact API | Source |
|---|---|---|
| Python floor raised; 3.9 dropped | `python_requires = >= 3.10` | [setup.cfg#L37](https://github.com/Project-MONAI/MONAI/blob/1.6.0/setup.cfg), [whatsnew](https://monai.readthedocs.io/en/stable/whatsnew_1_6.html) |
| PyTorch floor raised | `torch>=2.8.0` | [requirements.txt](https://github.com/Project-MONAI/MONAI/blob/1.6.0/requirements.txt) |
| Auto3DSeg algo serialization moved from pickle to JSON; pickle gated behind an env var | `MONAI_ALLOW_PICKLE`, read by `MONAIEnvVars.allow_pickle()`; `algo_to_pickle` now `@deprecated(since="1.6")`; new `algo_to_json` / `algo_from_json` | [auto3dseg/utils.py](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/auto3dseg/utils.py), [misc.py](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/utils/misc.py), [PR #8695](https://github.com/Project-MONAI/MONAI/pull/8695) |
| `NumpyReader` no longer unpickles by default | `NumpyReader(..., allow_pickle: bool = False, ...)`; raises `ValueError` if pickled data is encountered while `False` | [image_reader.py#L1241](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/data/image_reader.py), [PR #8875](https://github.com/Project-MONAI/MONAI/pull/8875) |
| nnUNet runner shell-command hardening | `monai.apps.nnunet.nnunetv2_runner.nnUNetV2Runner` — no longer concatenates unvalidated `dataset_name_or_id` into a `shell=True` command line | [PR #8885](https://github.com/Project-MONAI/MONAI/pull/8885), [GHSA-rghg-q7wp-9767](https://github.com/advisories/GHSA-rghg-q7wp-9767) |
| `ConfigParser` nested attribute access | `ConfigParser.__getattr__` now returns a `_ConfigProxy` for dict/list results, so `parser.network_def.in_channels` chains; supports indexing and assignment | [config_parser.py#L325](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/bundle/config_parser.py), [PR #8858](https://github.com/Project-MONAI/MONAI/pull/8858) |
| WSI reading at a physical resolution | `WSIReader(..., mpp=..., mpp_rtol=0.05, mpp_atol=0.0)`, plus `get_mpp(wsi, level)`; only one of `level`, `mpp`, `power` may be given | [wsi_reader.py](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/data/wsi_reader.py), [PR #7574](https://github.com/Project-MONAI/MONAI/pull/7574) |
| Crops in world coordinates | `TransformPointsWorldToImaged`, `TransformPointsImageToWorldd` (both exported from `monai.transforms`); `SpatialCropd` now accepts *string dict keys* for `roi_center` / `roi_size` / `roi_start` / `roi_end`, resolved at call time | [transforms/\_\_init\_\_.py](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/transforms/__init__.py), [croppad/dictionary.py#L420](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/transforms/croppad/dictionary.py), [PR #8794](https://github.com/Project-MONAI/MONAI/pull/8794) |
| New loss: Matthews correlation coefficient | `MCCLoss` (`monai.losses.mcc_loss`) | [losses/\_\_init\_\_.py#L40](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/losses/__init__.py), [PR #8785](https://github.com/Project-MONAI/MONAI/pull/8785) |
| New loss: AUC margin — **name differs from the release page** | Shipped class is `AUCMLoss` in `monai/losses/aucm_loss.py`, exported as `AUCMLoss`. The what's-new page calls it `AUCMarginLoss`; that identifier does not exist in the 1.6.0 tree. | [losses/\_\_init\_\_.py#L15](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/losses/__init__.py), [aucm_loss.py#L21](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/losses/aucm_loss.py), [PR #8719](https://github.com/Project-MONAI/MONAI/pull/8719) |
| New metric: embedding collapse detection | `EmbeddingCollapseMetric` and the functional `compute_embedding_collapse` (`monai.metrics.embedding_collapse`) | [embedding_collapse.py](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/metrics/embedding_collapse.py), [PR #8815](https://github.com/Project-MONAI/MONAI/pull/8815) |
| clDice losses aligned to `DiceLoss` | `SoftclDiceLoss`, `SoftDiceclDiceLoss` now take `reduction`, `smooth_nr`, `smooth_dr`, `batch` | [whatsnew](https://monai.readthedocs.io/en/stable/whatsnew_1_6.html), [PR #8703](https://github.com/Project-MONAI/MONAI/pull/8703) |
| Zip Slip hardening on NGC private bundle download | `_extract_zip` replaces a bare `zipfile.ZipFile(...).extractall()` in `_download_from_ngc_private` | [scripts.py](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/bundle/scripts.py), [PR #8682](https://github.com/Project-MONAI/MONAI/pull/8682) |
| `Invertd` / `Compose.inverse()` no longer assume the tail history entry | `TraceableTransform._transforms_match` added; `get_most_recent_transform` searches backward for a match instead of popping the tail | [inverse.py](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/transforms/inverse.py), [PR #8651](https://github.com/Project-MONAI/MONAI/pull/8651), [issue #8396](https://github.com/Project-MONAI/MONAI/issues/8396) |
| `RandSimulateLowResolution` no longer toggles global `set_track_meta` | now uses `torch.nn.functional.interpolate` on a `convert_to_tensor(img, track_meta=False)` tensor | [PR #8837](https://github.com/Project-MONAI/MONAI/pull/8837), [issue #8409](https://github.com/Project-MONAI/MONAI/issues/8409) |

## What breaks or needs action for us

**The PyTorch 2.8 floor is the blocker, not Python.** `torch>=2.8.0` versus our base image's
2.4.1. Adopting 1.6.0 means rebasing `Dockerfile` on a `pytorch/pytorch` image with torch
≥ 2.8, which also moves the CUDA and cuDNN versions and therefore needs re-verification of
the `runtime: nvidia` path on the GPU host. Bundle weights themselves are version-agnostic,
but a bundle that was trained and published against an older torch may hit `torch.load`
`weights_only` behaviour differences — we have not tested that and should not assume it.

**The Python 3.10 floor is probably already satisfied, but is unverified here.** MONAI 1.6.0
sets `python_requires = >= 3.10`
([setup.cfg](https://github.com/Project-MONAI/MONAI/blob/1.6.0/setup.cfg)). I did not pull
`pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime` to read its interpreter version, so I am not
asserting what it is. Since the base image has to change for torch anyway, this resolves
itself.

**Auto3DSeg pickle change: no action.** We never call `algo_to_pickle` / `algo_from_pickle`
and never touch Auto3DSeg. If a *bundle* we run were to load a legacy `algo_object.pkl`, it
would now fail with `RuntimeError` unless `MONAI_ALLOW_PICKLE=1` is set
([auto3dseg/utils.py](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/auto3dseg/utils.py)).
Do not set that variable in the image; if a specific bundle ever needs it, set it for that
bundle only and record why.

**`NumpyReader` default change: watch for it, do not pre-empt it.** Any bundle whose
inference config constructs a `NumpyReader` (or lets `LoadImaged` fall through to it) and
whose inputs are `.npy`/`.npz` containing pickled objects will now raise `ValueError`
instead of loading
([image_reader.py](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/data/image_reader.py)).
We feed NIfTI, so our own staging path in `run_bundle.sh` — which explicitly skips anything
that is not `.nii` or `.nii.gz` — is unaffected. This is a bundle-side risk, not a
runner-side one. The failure would be loud, which is better than our usual silent-empty-loader
failure mode.

**`monai.bundle run` of an existing Model Zoo bundle: no signature change found.** `download()`
and `run()` take the same parameters in 1.5.0 and 1.6.0, and `DEFAULT_DOWNLOAD_SOURCE`
(`BUNDLE_DOWNLOAD_SRC`, default `"monaihosting"`) is unchanged. Our `--config_file`,
`--bundle_root`, `--dataset_dir`, `--output_dir` invocation should carry over as-is.

**One quiet `ConfigParser` behaviour change to be aware of.** In 1.5.0,
`ConfigParser.__getattr__` returned `self.get_parsed_content(id)` directly. In 1.6.0 it
returns `_wrap_parsed(...)`, so dict and list results come back wrapped in a `_ConfigProxy`
rather than as a plain `dict`/`list`
([1.5.0](https://github.com/Project-MONAI/MONAI/blob/1.5.0/monai/bundle/config_parser.py),
[1.6.0](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/bundle/config_parser.py)).
Code doing `isinstance(parser.some_key, dict)` would change behaviour. We do not use the
Python API — we shell out to the CLI — so this does not affect us, but it could affect a
bundle's own `scripts/` module.

## What we could use

We are a wrapper, not a builder: we run other people's bundles and measure the masks that
come out. Most of 1.6.0 is training-side and therefore not ours.

- **`ConfigParser` dot access** — genuinely tempting but not for the reason it looks. Our
  glob-extraction step in `run_bundle.sh` currently regexes `@dataset_dir + '...'` out of the
  raw JSON/YAML with `re.compile(r"@dataset_dir\s*\+\s*'([^']+)'")`. Replacing that with a
  real `ConfigParser` would be more robust than a regex, but dot-notation is cosmetic there;
  the substantive win would be using `ConfigParser` at all, which is available today on 1.5.0.
  Not a reason to upgrade.
- **Global/world-coordinate crops** (`TransformPointsWorldToImaged`, string-key `SpatialCropd`)
  — not relevant. We do not author transform pipelines; the bundle does. This would matter
  only if we ever added an ROI input to the XNAT command, at which point it is the right tool.
- **`MCCLoss`, `AUCMLoss`, `EmbeddingCollapseMetric`** — training-side. Not relevant to this
  repo. Worth knowing about if we ever build a bundle rather than run one, and `MCCLoss` is
  the interesting one for imbalanced segmentation.
- **WSI microns-per-pixel** (`WSIReader(mpp=...)`) — not relevant to this repo, which is
  volumetric NIfTI. Relevant to any future digital-pathology container, where scanner-
  independent resolution is exactly the problem you hit first.
- **`Invertd` history-matching fix (PR #8651)** — relevant in principle: bundles that append
  post-processing after `Invertd` previously failed with an ID mismatch. We have not seen this
  on `spleen_ct_segmentation`. See the next section for why this is *not* the MuscleMap bug.

## Security advisories

Both were published 2026-08-18 and both name **1.6.0 as the first patched version**, with
everything `< 1.6.0` affected. **Our pinned 1.5.0 is inside both affected ranges.**

| Advisory | Summary | CWE / severity | Affected | Fixed in | Reachable from our code? |
|---|---|---|---|---|---|
| [GHSA-rghg-q7wp-9767](https://github.com/advisories/GHSA-rghg-q7wp-9767) | OS command injection: `nnUNetV2Runner` concatenates YAML-supplied `dataset_name_or_id` into a `subprocess` call with `shell=True`, so shell metacharacters execute | CWE-78, high (no CVSS score published) | `< 1.6.0` | `1.6.0` | No. We never import `monai.apps.nnunet`, and the attack requires loading an attacker-supplied YAML config into `nnUNetV2Runner`. |
| [GHSA-qxq5-qhx6-94qw](https://github.com/advisories/GHSA-qxq5-qhx6-94qw) | `algo_from_pickle()` RCE via `pickle.loads()` on an attacker-supplied `.pkl`. Filed as an *incomplete fix* report: the earlier [GHSA-89gg-p5r5-q6r4](https://github.com/advisories/GHSA-89gg-p5r5-q6r4) claimed a 1.5.2 patch, but `monai/auto3dseg/utils.py` was unchanged | CWE-502, high, CVSS 3.1 base 7.8 (`AV:L/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H`) | `< 1.6.0` | `1.6.0` | No. Requires calling `algo_from_pickle` on an untrusted path; we never touch Auto3DSeg. |

Both fixes are in 1.6.0 only — there is no backport release. The practical read: neither is
exploitable through this container as written, but both will show up in an image scan
against the 1.5.0 pin, and the remediation the scanner will demand is 1.6.0, which forces the
torch rebase.

One attribution inconsistency worth recording rather than resolving: the what's-new page says
*both* the Auto3DSeg pickle→JSON migration *and* the `NumpyReader` `allow_pickle` change
"address GHSA-qxq5-qhx6-94qw"
([whatsnew](https://monai.readthedocs.io/en/stable/whatsnew_1_6.html)). The advisory text
itself describes only `algo_from_pickle` in `monai/auto3dseg/utils.py` and says nothing about
`NumpyReader`. The `NumpyReader` change ([PR #8875](https://github.com/Project-MONAI/MONAI/pull/8875))
looks like defence-in-depth done alongside, not a fix for the reported vulnerability. I am not
resolving which the maintainers meant.

## Not established / not fixed

**The inverse-transform tracing failure MuscleMap 1.3.38 hit on 2026-09-02 is NOT fixed in
1.6.0.** This is established, not merely unverified:

- The exact symptom is tracked upstream as
  [issue #7701, "Metadata/Tracing tracking fails after catching an exception"](https://github.com/Project-MONAI/MONAI/issues/7701),
  opened 2024-04-23 and **still open**. The report is our scenario almost verbatim: catch a
  CUDA OOM during post-processing, retry on CPU, and every subsequent `Invertd` call raises
  `RuntimeError("Transform Tracing must be enabled to get the most recent transform.")` until
  a new dataloader is constructed. The reporter's pipeline is `Spacingd` under `Invertd`,
  same as ours.
- The root cause, per the fix PR, is that
  `TraceableTransform.trace_transform()` is a `@contextmanager` that restores `self.tracing`
  only after a normal `yield`, with no `try`/`finally` — so an exception raised inside the
  block permanently leaks the temporary tracing value. **This code is unchanged in 1.6.0**:
  [inverse.py L403-409](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/transforms/inverse.py)
  is still `prev = self.tracing; self.tracing = to_trace; yield; self.tracing = prev`.
- The guard that raises the error is textually identical in 1.5.0 (line 336) and 1.6.0
  (line 361).
- The fix is [PR #9019](https://github.com/Project-MONAI/MONAI/pull/9019), opened 2026-07-25
  against `dev` — six weeks *after* 1.6.0 shipped — and it is **open and unmerged** as of
  2026-09-02. (A duplicate, [PR #9013](https://github.com/Project-MONAI/MONAI/pull/9013), is
  closed.) There is therefore no released MONAI version containing this fix.

Do not upgrade to 1.6.0 expecting this to go away. The two 1.6.0 changes that look adjacent
are both something else:
[PR #8651](https://github.com/Project-MONAI/MONAI/pull/8651) fixes an *ID mismatch* when
post-processing appends history entries (a different exception, raised from
`check_transforms_match`), and
[PR #8837](https://github.com/Project-MONAI/MONAI/pull/8837) removes a thread-unsafe global
`set_track_meta` toggle from `RandSimulateLowResolution` — the `track_meta` flag, not the
`tracing` flag.

Also not established:

- **Why the MuscleMap process exited 0 with no output.** Nothing in the MONAI sources
  explains a zero exit code after this exception; that is a MuscleMap-side error-handling
  question, not a MONAI one. Not investigated here.
- **The Python version of `pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime`.** Not pulled, not
  asserted.
- **`ConfigParser` key-separator notation in the release-page example.** The what's-new page
  writes `parser["network_def.in_channels"]` as the bracket-form equivalent, but
  `ID_SEP_KEY = "::"`
  ([bundle/utils.py#L36](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/bundle/utils.py))
  and the in-code docstring gives
  `parser.training.trainer.max_epochs` ≡ `parser.get_parsed_content("training::trainer::max_epochs")`
  ([config_parser.py#L325](https://github.com/Project-MONAI/MONAI/blob/1.6.0/monai/bundle/config_parser.py)).
  The dotted bracket form in the release note appears not to match the separator the code
  uses. I did not run it to find out which is right.
- **`AUCMarginLoss` vs `AUCMLoss`.** The release page's name does not exist in the tag; the
  shipped name is `AUCMLoss`. `AUCMLoss` is also absent from
  [docs/source/losses.rst](https://github.com/Project-MONAI/MONAI/blob/1.6.0/docs/source/losses.rst),
  which documents `MCCLoss` but not the AUC loss. Whether the class will be renamed to match
  the announcement is unknown.
- **Whether any specific Model Zoo bundle actually runs unchanged under 1.6.0.** Not tested.
  `spleen_ct_segmentation` is our only end-to-end-verified bundle (README records 2026-08-31
  on 1.5.0) and would need re-running against a 1.6.0 image before we claim anything.

## Related repo

`xnat_seg_wrapup` is unaffected by any of this. Its `Dockerfile` is `python:3.12-slim` with
`nibabel`, `numpy`, `pydicom`, `highdicom` and no torch; `pyproject.toml` lists the same four
dependencies. It reads a MONAI bundle's `metadata.json` as plain JSON —
`load_monai_metadata_json` in `segwrapup/labels.py` walks
`network_data_format.outputs.*.channel_def` with `json.loads` — and never imports the `monai`
package. A MONAI version change cannot reach it. The only thing that could is a change to the
*bundle metadata schema*, and I found no evidence of one in the 1.6.0 release notes.
