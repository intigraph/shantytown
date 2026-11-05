#!/usr/bin/env bash
set -euo pipefail
# Keep recorded bytes portable without rewriting the captured output.
if [ -t 1 ]; then
    stty -onlcr
fi
# BASE_SOURCE is an immutable extraction of the base package, not an installation.
printf '%s\n' 'BASE 15ddda51: squash landed, remote head deleted; then one new unpublished commit'
python3 demo.py "${BASE_SOURCE:?Set BASE_SOURCE to the base source extraction}"
printf '%s\n' 'CANDIDATE: same real Git topology and explicit merged-PR fixture'
python3 demo.py
