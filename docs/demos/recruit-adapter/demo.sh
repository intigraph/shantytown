#!/usr/bin/env bash
set -euo pipefail
: "${RECRUIT_DEMO_BASE:?supply the retained base package directory}"
printf '%s\n' 'Same verified-wake routing input; base source:'
python3 docs/demos/recruit-adapter/run.py "$RECRUIT_DEMO_BASE"
printf '%s\n' 'Candidate source; isolated policy and mocked enrollment/readiness/controller:'
python3 docs/demos/recruit-adapter/run.py .
