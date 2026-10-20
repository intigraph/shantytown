# Short deferred plates occupy feed capacity

The same modeled live idle pane owns eight short-deferred items. Eight repeated
Stop-policy observations falsely block the coordinator before the change (8),
and none do afterward (0). Removing those items leaves a genuinely empty plate:
its positive control still blocks on dispatchable work in both versions.

Base: `f8b788eb5c0e2df182285c0f6a8e001004f82b66`.
Candidate implementation: `2263715119780bfb5c1061e48a43b4e0c3feea2c`;
the following recording commit adds only these demo artifacts.

This is a Files-backed disposable fixture with NullPanes and a fixed UTC clock,
not historical item-state replay or installed acceptance. The stop policy and
feed selector are real; pane observations, wiring, budget and pool are modeled.
No real agent, scheduler, inbox or remote board is changed. Historical defer
states still need separate verification before a historical replay claim.

Run `python3 docs/probes/pr-demos/busy-wait/record.py` from the repository root
with the declared pytest test dependency available. Download
[output.log](output.log) and [timing.log](timing.log), then replay with
`scriptreplay --log-out output.log --log-timing timing.log` (util-linux).
Playback was verified locally; the output log is also a readable transcript.
These small sanitized recordings follow the existing demo-directory retention.
