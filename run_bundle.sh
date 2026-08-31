#!/usr/bin/env bash
# Download a MONAI Model Zoo bundle and run its inference config.
# Configuration via environment (set by the CS command definition):
#   BUNDLE_NAME     required, e.g. spleen_ct_segmentation
#   BUNDLE_VERSION  optional version pin
#   EXTRA_ARGS      optional extra "monai.bundle run" overrides (whitespace-split)
#   INPUT_DIR       default /input
#   OUTPUT_DIR      default /output
#   BUNDLE_DIR      default /bundles
set -euo pipefail

BUNDLE_NAME="${BUNDLE_NAME:?BUNDLE_NAME is required}"
BUNDLE_VERSION="${BUNDLE_VERSION:-}"
EXTRA_ARGS="${EXTRA_ARGS:-}"
INPUT_DIR="${INPUT_DIR:-/input}"
OUTPUT_DIR="${OUTPUT_DIR:-/output}"
BUNDLE_DIR="${BUNDLE_DIR:-/bundles}"

echo "=== monai-bundle-runner ==="
echo "bundle:  ${BUNDLE_NAME} ${BUNDLE_VERSION:-(latest)}"
echo "input:   ${INPUT_DIR}"
echo "output:  ${OUTPUT_DIR}"

if [ -z "$(ls -A "${INPUT_DIR}" 2>/dev/null)" ]; then
    echo "ERROR: input directory ${INPUT_DIR} is empty" >&2
    exit 1
fi

download_args=("${BUNDLE_NAME}" --bundle_dir "${BUNDLE_DIR}")
if [ -n "${BUNDLE_VERSION}" ]; then
    download_args+=(--version "${BUNDLE_VERSION}")
fi
python -m monai.bundle download "${download_args[@]}"

BUNDLE_ROOT="${BUNDLE_DIR}/${BUNDLE_NAME}"
CONFIG=""
for candidate in configs/inference.json configs/inference.yaml configs/inference.yml; do
    if [ -f "${BUNDLE_ROOT}/${candidate}" ]; then
        CONFIG="${BUNDLE_ROOT}/${candidate}"
        break
    fi
done
if [ -z "${CONFIG}" ]; then
    echo "ERROR: no inference config found in ${BUNDLE_ROOT}/configs" >&2
    ls -R "${BUNDLE_ROOT}/configs" >&2 || true
    exit 1
fi
echo "config:  ${CONFIG}"

# Many bundles glob a subdirectory of dataset_dir (MSD layout, e.g.
# @dataset_dir + '/imagesTs/*.nii.gz'). XNAT mounts a flat resource dir, so
# detect the expected sub-path from the config and stage symlinks to match.
DATASET_DIR="${INPUT_DIR}"
SUBDIR=$(python - "${CONFIG}" <<'PYEOF'
import json, re, sys, os
try:
    import yaml
except ImportError:
    yaml = None
path = sys.argv[1]
with open(path) as f:
    cfg = json.load(f) if path.endswith(".json") else yaml.safe_load(f)
pattern = re.compile(r"@dataset_dir\s*\+\s*'([^']+)'")
def walk(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)
    elif isinstance(node, str):
        m = pattern.search(node)
        if m:
            yield m.group(1)
for suffix in walk(cfg):
    d = os.path.dirname(suffix)
    if d and d != "/":
        print(d.lstrip("/"))
        break
PYEOF
)
if [ -n "${SUBDIR}" ]; then
    echo "staging: bundle expects dataset_dir/${SUBDIR}, symlinking input files"
    STAGED=/tmp/staged-input
    mkdir -p "${STAGED}/${SUBDIR}"
    find "${INPUT_DIR}" -type f -exec ln -s {} "${STAGED}/${SUBDIR}/" \;
    DATASET_DIR="${STAGED}"
fi

run_args=(
    --config_file "${CONFIG}"
    --bundle_root "${BUNDLE_ROOT}"
    --dataset_dir "${DATASET_DIR}"
    --output_dir "${OUTPUT_DIR}"
)
if [ -n "${EXTRA_ARGS}" ]; then
    # shellcheck disable=SC2206
    run_args+=(${EXTRA_ARGS})
fi

python -m monai.bundle run "${run_args[@]}"

echo "=== output files ==="
find "${OUTPUT_DIR}" -type f | head -50
if [ -z "$(ls -A "${OUTPUT_DIR}" 2>/dev/null)" ]; then
    echo "ERROR: bundle produced no output in ${OUTPUT_DIR}" >&2
    exit 1
fi
echo "=== done ==="
