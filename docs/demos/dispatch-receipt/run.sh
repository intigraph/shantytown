#!/usr/bin/env bash
set -euo pipefail
: "${DEMO_BASE:?Set DEMO_BASE to an extracted base source tree}"
: "${DEMO_CANDIDATE:?Set DEMO_CANDIDATE to the candidate source tree}"
cd -- "$(dirname -- "$0")"
echo 'Isolated library fixture; actual Dispatcher and file tracker; substituted terminal.'
echo 'Base: 9b08512c078632eb54406fd1d6027aeb9f800fc1'
echo '$ PYTHONPATH="$DEMO_BASE" python3 probe.py --expect base'
PYTHONPATH="$DEMO_BASE" python3 probe.py --expect base
echo 'Candidate behavior: b5dca181 (dispatch receipt integration and runtime binding)'
echo '$ PYTHONPATH="$DEMO_CANDIDATE" python3 probe.py --expect candidate'
PYTHONPATH="$DEMO_CANDIDATE" python3 probe.py --expect candidate
