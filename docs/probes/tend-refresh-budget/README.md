# Tend refresh budget probe

This source-only fixture gives each project refresh a synthetic 31-second cost.
It creates no sessions and performs no Git operations or network requests.
Run from the checkout root:

```sh
python3 -c "exec(compile(open('docs/probes/tend-refresh-budget/probe.py').read(), 'probe.py', 'exec'))"
```

Observed against base `c1f97f364a6059df8c79dcdb9c0736bd1ee92afb`:

```text
Refreshed trees and remote-retirement setting: [('first', True), ('second', True), ('third', True)]
Warnings: []
Synthetic elapsed seconds: 93.0
```

Observed against this candidate:

```text
Refreshed trees and remote-retirement setting: [('first', False)]
Warnings: ['tend source refresh budget exhausted; remaining worktrees deferred']
Synthetic elapsed seconds: 31.0
```

This is a readable transcript, not a recording. No terminal recording was captured.
It demonstrates the worktree maintenance policy with injected operations; it does
not establish real network latency, deployment, admission release or fleet recovery.
The regression tests also exercise a local Git worktree with a failing remote
retirement sentinel: tend refresh succeeds without that scan, while explicit
refresh reaches it. Retain this small fixture with the source change.


## Current source reconciliation

A fresh replay compares main `00aeb887d5ec2f8575283bd1c8eca5bbf09aa795`
with retained candidate `ab0f0f356fc417189890f50e7b97b99f43470d50`.
[output.log](output.log) and [timing.log](timing.log) are a replayable terminal
recording; playback was checked with `scriptreplay`. Download both and run:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

[compare.py](compare.py) loads only the named refresh function from each Git
revision into the same isolated fixture. It injects the refresh operation and
clock; it does not run real source maintenance, admission or session recovery.
The current replay again shows three refreshes/93 simulated seconds becoming
one refresh/31 simulated seconds with remote retirement disabled. The separate
regression controls exercise real local Git operations. The recording remains
with this small probe so the evidence survives branch cleanup.
