# Busy Codex submission

Synthetic library protocol fixture, with every pane read, key send and journal write mocked. The exact owned busy composer changes its first submission key from Enter to Tab. A fresh foreign composer changes from Enter to no submission key. A queued preview remains UNVERIFIED on both revisions; this is not delivery or installed acceptance.

Base: `831a2f0b9cda31c999c4e12d6809b184aaa2e3f4`.
Implementation: `ca6cf1354d5667676d58e0fc61376ee3352739c5`.
The later demo-only commit does not change the implementation.

Run from the repository root:

```sh
PYTHONPATH=. python docs/pr-demos/codex-busy-tab.py --revision 831a2f0
PYTHONPATH=. python docs/pr-demos/codex-busy-tab.py --revision ca6cf135
scriptreplay --log-out docs/pr-demos/codex-busy-tab.typescript --log-timing docs/pr-demos/codex-busy-tab.timing
```

[Output recording / readable transcript](codex-busy-tab.typescript), [timing](codex-busy-tab.timing), [reproducer](codex-busy-tab.py). Download the output and timing files for terminal replay; no inline player is claimed. Replay and raw output were checked. These small sanitized artifacts are retained with the repository's existing PR demos.
