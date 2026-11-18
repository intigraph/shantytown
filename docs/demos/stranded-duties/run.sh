#!/usr/bin/env bash
set -euo pipefail
: "${DUTY_DEMO_BASE_SOURCE:?set to an isolated archive of the documented base}"
echo 'BASE: same synthetic stopped worker, supported queue, external reservation and ASK'
python3 docs/demos/stranded-duties/probe.py --source "$DUTY_DEMO_BASE_SOURCE"
echo
echo 'CANDIDATE: same input; two existing sweep passes; no real board or process changes'
python3 docs/demos/stranded-duties/probe.py --source .
