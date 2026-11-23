#!/usr/bin/env bash
set -euo pipefail
: "${DEMO_BASE_ROOT:?point to the isolated base source export described in README}"
printf 'BASE ddfc3b53113a92b660f1528e99ee9a0332f52f50\n'
(cd "$DEMO_BASE_ROOT" && python3 -B docs/demos/sdk-display-coalescing/demo.py)
printf 'CANDIDATE functional source 23a0d3ffd8bd0a98ec1923e00d23c5dec21a7e89\n'
python3 -B docs/demos/sdk-display-coalescing/demo.py
