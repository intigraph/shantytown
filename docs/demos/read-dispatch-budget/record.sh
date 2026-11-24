#!/usr/bin/env bash
set -euo pipefail
: "${DEMO_BASE_ROOT:?point to the isolated base export described in README}"
printf 'BASE 556417ebfb6f749f274b07212fec0996add948ec\n'
(cd "$DEMO_BASE_ROOT" && python3 -B docs/demos/read-dispatch-budget/demo.py)
printf 'CANDIDATE functional source b068c46ad6f37c6fbe40a302329338e672d27af2\n'
python3 -B docs/demos/read-dispatch-budget/demo.py
