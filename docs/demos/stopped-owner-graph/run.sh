#!/usr/bin/env bash
set -euo pipefail
source_root=$(git rev-parse --show-toplevel)
base=71cd44705c1d41cb5ef7a10cc588143da4a0b4b0
candidate=$(git rev-parse HEAD)
base_tree=$(mktemp -d -t owned-demo-base.XXXXXXXX)
git archive "$base" | tar -x -C "$base_tree"
printf 'Synthetic in-memory graph receiver; no HTTP, deployment or native expiry claim.\n'
printf 'BASE %s\n' "$base"
python3 "$source_root/docs/demos/stopped-owner-graph/demo.py" "$base_tree"
printf 'CANDIDATE %s\n' "$candidate"
python3 "$source_root/docs/demos/stopped-owner-graph/demo.py" "$source_root"
printf 'Demo completed. The temporary base archive is retained for inspection.\n'
