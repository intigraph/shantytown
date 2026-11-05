#!/usr/bin/env bash
set -euo pipefail
if [ -t 1 ]; then stty -onlcr; fi
printf '%s\n' 'BASE 1b32b5e: identical synthetic context, no HTTP'
python3 probe.py "${BASE_SOURCE:?immutable base package extraction required}"
printf '%s\n' 'CANDIDATE: same helper, complete and incomplete context'
python3 probe.py "${CANDIDATE_SOURCE:?candidate source required}"
