#!/bin/sh
set -eu
: "${DEMO_BASE_ROOT:?set the e46e8cfd base checkout}"
root=$(pwd)
printf 'BASE e46e8cfd: ordinary read behind processing ACKs\n'
PYTHONPATH="$DEMO_BASE_ROOT" PYTHONDONTWRITEBYTECODE=1 python3 "$root/docs/demos/inbox-processing/starvation-probe.py"
printf '\nCANDIDATE 3c589b99: eligible selection repair\n'
PYTHONPATH="$root" PYTHONDONTWRITEBYTECODE=1 python3 "$root/docs/demos/inbox-processing/starvation-probe.py"
