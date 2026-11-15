#!/bin/sh
set -eu
: "${DEMO_BASE_ROOT:?set DEMO_BASE_ROOT to a checkout of bfc8427a}"
root=$(pwd)
printf 'Synthetic local inbox probe; no production messages\n'
printf 'BASE bfc8427a: transport ACK is not processing ACK\n'
PYTHONPATH="$DEMO_BASE_ROOT" PYTHONDONTWRITEBYTECODE=1 python3 "$root/docs/demos/inbox-processing/probe.py" base
printf '\nCANDIDATE: explicit processing ACK/DEFER\n'
PYTHONPATH="$root" PYTHONDONTWRITEBYTECODE=1 python3 "$root/docs/demos/inbox-processing/probe.py" candidate
