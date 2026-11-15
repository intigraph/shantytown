#!/bin/sh
set -eu
: "${PACING_BEFORE_SOURCE:?explicit baseline checkout required}"
: "${PACING_AFTER_SOURCE:?explicit candidate checkout required}"
: "${PACING_PYTHON:=python3}"
demo=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
echo 'BEFORE: same 85 stopped-owner fixture rows'
"$PACING_PYTHON" -B "$demo/probe.py" "$PACING_BEFORE_SOURCE"
echo 'AFTER: same 85 stopped-owner fixture rows'
"$PACING_PYTHON" -B "$demo/probe.py" "$PACING_AFTER_SOURCE"
