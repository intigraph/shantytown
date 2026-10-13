#!/usr/bin/env bash
set -euo pipefail
repo=$(git rev-parse --show-toplevel)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
git archive aaeecc697d68e2a7217186aadeb15c1942af4b4b shantytown | tar -xf - -C "$scratch"
python3 -c 'import sys,runpy; sys.path.insert(0,sys.argv[1]); runpy.run_path(sys.argv[2],run_name="__main__")' "$scratch" "$repo/docs/probes/pr-demos/gate-backstop/blocked.py"
python3 -c 'import sys,runpy; sys.path.insert(0,sys.argv[1]); runpy.run_path(sys.argv[2],run_name="__main__")' "$repo" "$repo/docs/probes/pr-demos/gate-backstop/blocked.py"
