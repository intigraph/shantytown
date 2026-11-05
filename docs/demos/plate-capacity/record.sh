#!/usr/bin/env bash
set -euo pipefail
: "${PLATE_BASELINE:?Set PLATE_BASELINE to a checkout of 188938041424e9dff3a233580e7742ad1de2bf7a}"
printf 'BASE 188938041424e9dff3a233580e7742ad1de2bf7a; isolated fixture\n'
PYTHONPATH="$PLATE_BASELINE" python3 docs/demos/plate-capacity/demo.py
printf '\nCANDIDATE; same isolated fixture and probe\n'
PYTHONPATH=. python3 docs/demos/plate-capacity/demo.py
