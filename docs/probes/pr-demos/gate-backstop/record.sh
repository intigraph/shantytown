#!/usr/bin/env bash
set -euo pipefail
printf 'Private fixture: exact paper -> release chain; target explicitly deferred.\n'
printf 'BASE 28a4f7fc: same probe, no live store or pane writes\n'
python3 docs/probes/pr-demos/gate-backstop/probe.py "$GATE_DEMO_BASE"
printf 'CANDIDATE: same probe, explicit technical gate lint plus persisted chain event\n'
python3 docs/probes/pr-demos/gate-backstop/probe.py .
