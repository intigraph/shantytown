#!/bin/sh
# Isolated source comparison: no network, notifications or real state.
set -eu
# Keep the recording LF-only without rewriting its byte-count timing.
if [ -t 1 ]; then stty -onlcr; fi
baseline=$(mktemp -d)
trap 'rm -rf "$baseline"' EXIT
git archive 195a7ef3 shantytown | tar -x -C "$baseline"
printf 'BASE 195a7ef3: identical isolated routing inputs\n'
PYTHONPATH="$baseline" python3 docs/pr-demos/deferral-recipient-diagnostics.py before
printf '\nCANDIDATE: identical isolated routing inputs\n'
PYTHONPATH=. python3 docs/pr-demos/deferral-recipient-diagnostics.py after
