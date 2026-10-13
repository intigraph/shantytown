#!/usr/bin/env bash
set -euo pipefail
task_demo_base=$(mktemp -d)
trap 'rm -rf "$task_demo_base"' EXIT
git archive 31605148230d shantytown | tar -x -C "$task_demo_base"
echo 'BASE 31605148230d, identical40-day future-gate input:'
python3 docs/demos/deferred-reading-list.py "$task_demo_base"
echo 'CANDIDATE, same input and command:'
python3 docs/demos/deferred-reading-list.py .
