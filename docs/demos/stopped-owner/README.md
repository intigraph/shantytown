# Stopped-owner escalation

Watch the same synthetic agent stop while holding two seeds, one P0/overdue.
The base records intent and sends zero lead notices. The candidate sends exactly
one notice containing both identifiers, while both seeds keep their owner.
The probe invokes the actual CLI stop function with in-memory panes and a fresh
temporary registry, owner reader and inbox. It never stops an actual agent.

Base: `b431498a5663c0fe75761eeb809aff107809d55b`. The recording names the exact implementation
commit; the later recording commit preserves its product bytes.
Run `python3 docs/demos/stopped-owner/record.py` with repository test dependencies.

[Output recording](output.log) and [timing](timing.log) are retained here as small
repository artifacts. Download both to replay with util-linux `scriptreplay
--log-out output.log --log-timing timing.log`; no inline player is assumed.
The log is also the readable transcript. Only generated fixture identifiers are
shown; private deployment configuration and paths are excluded.

This proves source behavior on a fixture, not installed delivery latency. Native
Quipu expiry/graph projection and the authoritative Brief panel remain unsupported
pending their governed contracts; actual operator-held crew are not test subjects.
