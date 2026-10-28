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
