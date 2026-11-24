#!/bin/sh
set -eu
: "${BEFORE_SRC:?bridge source checkout}" "${AFTER_SRC:?candidate source checkout}" "${DEMO_PARENT:?existing private parent with clean ancestry}"
PYTHON="${PYTHON:-python3}"
printf '%s\n' 'Same local directory-admission probe; before = bridge source, after = attended contract source.'
"$PYTHON" probe.py "$BEFORE_SRC" "$DEMO_PARENT"
"$PYTHON" probe.py "$AFTER_SRC" "$DEMO_PARENT"
