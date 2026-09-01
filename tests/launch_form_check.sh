#!/usr/bin/env bash
# Integration check: can the XNAT UI actually build a launch form for each wrapper?
#
# Static JSON validation cannot catch an input that resolves on paper but not
# against real data (e.g. a resource derived from the wrong parent). This hits
# GET /xapi/projects/{project}/wrappers/{id}/launch — the same call the "Run
# Containers" menu makes — so a wrapper that would show "Failed to load launch
# form: HTTP 400" fails here first.
#
# Usage:
#   tests/launch_form_check.sh <host> <user> <project> <session-id> [scan-id]
# Password is read from XNAT_PASS, or ~/.netrc for the host.
set -euo pipefail

HOST="${1:?usage: launch_form_check.sh <host> <user> <project> <session> [scan]}"
USER_NAME="${2:?missing user}"
PROJECT="${3:?missing project}"
SESSION="${4:?missing session id}"
SCAN="${5:-1}"
COMMAND_NAME="${COMMAND_NAME:-monai-bundle-runner}"

if [ -z "${XNAT_PASS:-}" ]; then
    XNAT_PASS=$(grep -A2 "machine ${HOST}" "${HOME}/.netrc" 2>/dev/null \
        | awk '/password/{print $2}' | head -1)
fi
[ -n "${XNAT_PASS:-}" ] || { echo "FAIL: no password (set XNAT_PASS)"; exit 1; }

auth=(-u "${USER_NAME}:${XNAT_PASS}")
api="${HOST}/xapi"

command_id=$(curl -s "${auth[@]}" "${api}/commands" \
    | python3 -c "
import json, sys
name = '${COMMAND_NAME}'
print(next((c['id'] for c in json.load(sys.stdin) if c['name'] == name), ''))
")
[ -n "${command_id}" ] || { echo "FAIL: command ${COMMAND_NAME} not installed"; exit 1; }
echo "command ${COMMAND_NAME} = ${command_id}"

wrappers=$(curl -s "${auth[@]}" "${api}/commands/${command_id}" \
    | python3 -c "
import json, sys
for wrapper in json.load(sys.stdin)['xnat']:
    context = ','.join(wrapper.get('contexts', []))
    print(wrapper['id'], wrapper['name'], context)
")

fail=0
while read -r wrapper_id wrapper_name contexts; do
    [ -n "${wrapper_id}" ] || continue
    case "${contexts}" in
        *imageScanData*) param="scan=/experiments/${SESSION}/scans/${SCAN}" ;;
        *imageSessionData*) param="session=/experiments/${SESSION}" ;;
        *) echo "SKIP ${wrapper_name}: unhandled context ${contexts}"; continue ;;
    esac

    body=$(curl -s "${auth[@]}" -G "${api}/projects/${PROJECT}/wrappers/${wrapper_id}/launch" \
        --data-urlencode "${param}" -w '\n%{http_code}')
    status="${body##*$'\n'}"
    payload="${body%$'\n'*}"

    if [ "${status}" = "200" ]; then
        echo "PASS ${wrapper_name} (${param})"
    else
        echo "FAIL ${wrapper_name} (${param}) -> HTTP ${status}"
        echo "     ${payload}" | head -3
        fail=1
    fi
done <<< "${wrappers}"

if [ "${fail}" -ne 0 ]; then
    echo "LAUNCH FORM CHECK FAILED"
    exit 1
fi
echo "ALL LAUNCH FORMS OK"
