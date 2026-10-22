#!/bin/sh
set -eu
: "${INBOX_BASELINE:?set INBOX_BASELINE to base 37e714e source checkout}"
printf 'BASE 37e714e; private source + native Seeds fixture\n'
PYTHONPATH="$INBOX_BASELINE" python3 -B docs/demos/inbox-graph/demo.py
printf '\nCANDIDATE working tree; private source + native Seeds fixture\n'
PYTHONPATH=. python3 -B docs/demos/inbox-graph/demo.py
