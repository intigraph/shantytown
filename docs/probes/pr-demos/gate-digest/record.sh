#!/bin/sh
set -eu
baseline_tree=$(mktemp -d)
trap 'rm -rf "$baseline_tree"' EXIT
git archive d37ff0e43717713a331a80e64a10d86ad4bd6282 shantytown | tar -x -C "$baseline_tree"
printf 'BEFORE: one admin turn per chain\n'
python3 docs/probes/pr-demos/gate-digest/probe.py "$baseline_tree"
printf 'AFTER: one digest per pass and a recorded-verdict cooldown\n'
python3 docs/probes/pr-demos/gate-digest/probe.py "$PWD"
