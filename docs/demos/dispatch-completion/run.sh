#!/usr/bin/env bash
set -euo pipefail
root=$(git rev-parse --show-toplevel)
base=f909de3e3ba445946545dd673f94edea1de2d0fd
candidate=864c433c02a6557355f72a0d23aa404a18c849a7
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
for revision in "$base" "$candidate"; do
  mkdir "$scratch/$revision"
  git -C "$root" archive "$revision" shantytown | tar -x -C "$scratch/$revision"
  printf '\nSource %s — synthetic pane, real receipt ledger and file CAS\n' "$revision"
  python3 "$root/scripts/demo-dispatch-completion.py" "$scratch/$revision"
done
