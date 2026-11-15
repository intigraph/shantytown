#!/bin/sh
set -eu
printf 'Before 2f889a20bdda611609edeb6f7f2f0f0dc31ebfae: same two work rows and four message rows\n'
python3 docs/demos/inbox-work-count/demo.py --source "${DEMO_BASE_SOURCE:?extract base first}"
printf '\nCandidate %s: same rows, real work keeps its inbox label\n' "$(git rev-parse HEAD)"
python3 docs/demos/inbox-work-count/demo.py
