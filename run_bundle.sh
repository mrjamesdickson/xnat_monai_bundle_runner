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

# Bundles glob a path under dataset_dir, e.g. @dataset_dir + '/imagesTs/*.nii.gz'.
# XNAT mounts a flat resource directory whose files may not match either the
# expected subdirectory or the expected compression (.nii vs .nii.gz), so read the
# glob out of the inference config and stage the inputs to match it.
DATASET_DIR="${INPUT_DIR}"
GLOB=$(python - "${CONFIG}" <<'PYEOF'
import json, re, sys
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
    print(suffix.lstrip("/"))
    break
PYEOF
)

if [ -n "${GLOB}" ]; then
    SUBDIR=$(dirname "${GLOB}")
    [ "${SUBDIR}" = "." ] && SUBDIR=""
    # expected extension from the glob's basename, e.g. "*.nii.gz" -> ".nii.gz"
    WANT_EXT=$(basename "${GLOB}" | sed 's/^\*//')
    STAGED=/tmp/staged-input
    TARGET="${STAGED}${SUBDIR:+/${SUBDIR}}"
    echo "staging: bundle globs '${GLOB}' -> staging inputs into ${TARGET}"
    mkdir -p "${TARGET}"

    staged_count=0
    while IFS= read -r src; do
        base=$(basename "${src}")
        case "${base}" in
            *.nii.gz) src_ext=".nii.gz" ;;
            *.nii)    src_ext=".nii" ;;
            *)        continue ;;   # skip sidecars (.json, catalogs, etc.)
        esac
        stem="${base%"${src_ext}"}"
        dest="${TARGET}/${stem}${WANT_EXT}"
        if [ "${src_ext}" = "${WANT_EXT}" ]; then
            ln -sf "${src}" "${dest}"
        elif [ "${src_ext}" = ".nii" ] && [ "${WANT_EXT}" = ".nii.gz" ]; then
            echo "  compressing ${base} to match expected ${WANT_EXT}"
            gzip -c "${src}" > "${dest}"
        elif [ "${src_ext}" = ".nii.gz" ] && [ "${WANT_EXT}" = ".nii" ]; then
            echo "  decompressing ${base} to match expected ${WANT_EXT}"
            gunzip -c "${src}" > "${dest}"
        else
            ln -sf "${src}" "${dest}"
        fi
        staged_count=$((staged_count + 1))
    done < <(find "${INPUT_DIR}" -type f)

    if [ "${staged_count}" -eq 0 ]; then
        echo "ERROR: no NIfTI files found in ${INPUT_DIR} to stage for glob '${GLOB}'" >&2
        ls -la "${INPUT_DIR}" >&2
        exit 1
    fi
    echo "staged ${staged_count} file(s)"
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

if [ -z "$(ls -A "${OUTPUT_DIR}" 2>/dev/null)" ]; then
    echo "ERROR: bundle produced no output in ${OUTPUT_DIR}" >&2
    exit 1
fi

echo "=== volumetrics ==="
# The report is a convenience layer: a bundle whose output is not a label map
# still succeeds, so never fail the run on report generation alone.
if ! BUNDLE_ROOT="${BUNDLE_ROOT}" OUTPUT_DIR="${OUTPUT_DIR}" \
     python /opt/runner/make_report.py; then
    echo "WARNING: volumetrics report failed; segmentation output is unaffected" >&2
fi

echo "=== output files ==="
find "${OUTPUT_DIR}" -type f | head -50
echo "=== done ==="
