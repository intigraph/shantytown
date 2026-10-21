#!/usr/bin/env bash
set -euo pipefail
# BASE_SOURCE is an immutable extraction of the base package, not an installation.
printf '%s\n' 'BASE 85fde581: squash landed, remote head deleted; then one new unpublished commit'
python3 demo.py "${BASE_SOURCE:?Set BASE_SOURCE to the base source extraction}"
printf '%s\n' 'CANDIDATE: same real Git topology and explicit merged-PR fixture'
python3 demo.py
