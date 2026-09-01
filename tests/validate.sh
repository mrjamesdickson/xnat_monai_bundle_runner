#!/usr/bin/env bash
# Static validation: command JSON sanity + the CS caret trap + shell syntax.
# Run locally or in CI; requires jq.
set -euo pipefail
cd "$(dirname "$0")/.."

fail=0

echo "--- command JSON is valid JSON"
for cmd in commands/*.json; do
    jq empty "$cmd" || { echo "FAIL: $cmd is not valid JSON"; fail=1; }
done

echo "--- required command fields present"
for cmd in commands/*.json; do
    for field in name image command-line; do
        val=$(jq -r --arg f "$field" '.[$f] // empty' "$cmd")
        [ -n "$val" ] || { echo "FAIL: $cmd missing $field"; fail=1; }
    done
done

echo "--- no carets in command-line (CS treats caret pairs as JSONPath; silent launch failure)"
for cmd in commands/*.json; do
    if jq -r '."command-line" // ""' "$cmd" | grep -q '\^'; then
        echo "FAIL: caret in command-line of $cmd"
        fail=1
    fi
done

echo "--- every env-var template has a matching input"
for cmd in commands/*.json; do
    inputs=$(jq -r '.inputs[].name' "$cmd")
    templates=$(jq -r '."environment-variables" // {} | .[]' "$cmd" | grep -o '#[a-z-]*#' | tr -d '#' | sort -u)
    for t in $templates; do
        echo "$inputs" | grep -qx "$t" || { echo "FAIL: $cmd env template #$t# has no matching input"; fail=1; }
    done
done

echo "--- output handlers reference declared outputs and mounts"
for cmd in commands/*.json; do
    outputs=$(jq -r '.outputs[].name' "$cmd")
    handled=$(jq -r '.xnat[]."output-handlers"[]."accepts-command-output"' "$cmd" | sort -u)
    for h in $handled; do
        echo "$outputs" | grep -qx "$h" || { echo "FAIL: $cmd handler references undeclared output $h"; fail=1; }
    done
done

# CS canonicalises this property to "as-a-child-of"; the documented
# "as-a-child-of-wrapper-input" is accepted on create but rejected on update,
# and a blank value only surfaces as a runtime upload failure.
echo "--- output handlers name a wrapper input that exists (as-a-child-of)"
for cmd in commands/*.json; do
    jq -r '
      .xnat[] |
      .name as $w |
      ([.["external-inputs"][]?.name] + [.["derived-inputs"][]?.name]) as $inputs |
      .["output-handlers"][]? |
      "\($w)\t\(.name)\t\(.["as-a-child-of"] // "")\t\($inputs | join(","))"
    ' "$cmd" | while IFS=$'\t' read -r wrapper handler parent inputs; do
        if [ -z "$parent" ]; then
            echo "FAIL: $cmd $wrapper/$handler has blank as-a-child-of"
            exit 1
        fi
        case ",$inputs," in
            *",$parent,"*) ;;
            *) echo "FAIL: $cmd $wrapper/$handler as-a-child-of '$parent' is not a wrapper input ($inputs)"; exit 1 ;;
        esac
    done || fail=1
done

echo "--- inputs that provide files for a mount derive from a data-bearing object"
for cmd in commands/*.json; do
    jq -r '
      .xnat[] | .name as $w |
      .["derived-inputs"][]? | select(.["provides-files-for-command-mount"]) |
      "\($w)\t\(.name)\t\(.["derived-from-wrapper-input"] // "")"
    ' "$cmd" | while IFS=$'\t' read -r wrapper input parent; do
        [ -n "$parent" ] || { echo "FAIL: $cmd $wrapper/$input provides files but derives from nothing"; exit 1; }
    done || fail=1
done

echo "--- shell scripts parse"
bash -n run_bundle.sh || { echo "FAIL: run_bundle.sh syntax"; fail=1; }

if [ "$fail" -ne 0 ]; then
    echo "VALIDATION FAILED"
    exit 1
fi
echo "ALL CHECKS PASSED"
