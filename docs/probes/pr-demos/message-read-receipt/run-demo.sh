#!/usr/bin/env bash
set -euo pipefail
: "${BASE_DIR:?set to a2b2dfc6 checkout}"
: "${CANDIDATE_DIR:?set to this proposal}"
echo 'Baseline a2b2dfc648925aac6450f25fff38c47b8c36f20a'
SOURCE_DIR="$BASE_DIR" python3 demo.py
echo
echo 'Candidate'
SOURCE_DIR="$CANDIDATE_DIR" python3 demo.py
