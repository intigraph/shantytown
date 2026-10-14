#!/bin/sh
set -eu
demo_base=$(mktemp -d /tmp/st-inbox-demo.XXXXXX)
trap 'rm -rf "$demo_base"' EXIT
# Fixed base makes the interrupted 96-message behavior reproducible.
git archive c2200662533bdc277f0be4b46def0787acadb637 shantytown | tar -x -C "$demo_base"
printf 'BASE c220066: 96-message scratch probe, 1.2s hard deadline\n'
python3 docs/demos/inbox-read/probe.py "$demo_base"
printf '\nBASE positive control: 3 messages\n'
python3 docs/demos/inbox-read/probe.py "$demo_base" --count 3
printf '\nCANDIDATE: same 96-message scratch probe and deadline\n'
python3 docs/demos/inbox-read/probe.py .
