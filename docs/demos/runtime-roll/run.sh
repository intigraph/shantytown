#!/bin/sh
set -eu
printf 'Base 195a7ef3: same installed-version fixture\n'
python3 scripts/demo-runtime-roll.py --source "${DEMO_BASE_SOURCE:?extract base shantytown source first}"
printf '\nCandidate %s: same installed-version fixture\n' "$(git rev-parse HEAD)"
python3 scripts/demo-runtime-roll.py
