#!/usr/bin/env bash
set -euo pipefail
: "${BASE_SOURCE:?set BASE_SOURCE to an extracted base tree}"
source_root=$(pwd)
python3 docs/demos/bare-source-hint/probe.py "$BASE_SOURCE" BEFORE
python3 docs/demos/bare-source-hint/probe.py "$source_root" AFTER
