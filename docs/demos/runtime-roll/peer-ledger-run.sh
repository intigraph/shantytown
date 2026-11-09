#!/bin/sh
set -eu
printf 'Before 677c4e238f439c085f1611202031bff62eda763c: fail first ledger write\n'
python3 docs/demos/runtime-roll/peer-ledger-gap.py --source "${DEMO_BASE_SOURCE:?extract base source first}"
printf '\nCandidate %s: same first-write failure\n' "$(git rev-parse HEAD)"
python3 docs/demos/runtime-roll/peer-ledger-gap.py
printf '\nCandidate: fail final ledger write after request\n'
python3 docs/demos/runtime-roll/peer-ledger-gap.py --fail-write 2
