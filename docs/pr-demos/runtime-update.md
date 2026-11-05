# Prefer replacement for an installed CLI update

The same isolated fixture runs against base
42700874c0ef2207b54caaea619ff9bd5e8f7096 and source
73d965549e0222e756af111606d115a03e51341c. Native metadata says the exact current
session runs Claude Code 2.1.317; a fixture executable reports installed 2.1.318.
The session is only 20k deep.

Before: no update preference and no idle prompt. After: `cycle` advice requires
process replacement; the actual CycleDriver prompts the idle fixture once with
`--no-in-place` and suppresses the repeat. Both versions stay silent when the
fixture is busy. Simulated fresh-session metadata at 2.1.318 removes the update
preference. Neither source creates a cycle request.

[Recording output](runtime-update.output), [timing](runtime-update.timing),
[reproducer](runtime-update.py). These small sanitized files are retained in the
existing demo directory. Download the recording pair and replay:

```sh
scriptreplay --log-out runtime-update.output --log-timing runtime-update.timing
python3 runtime-update.py --source /path/to/source-checkout
```

Playback was verified with util-linux scriptreplay. No inline player is claimed.
HOME, PATH executable, native records, launch stamp, stats database, pane state,
wiring and delivery sink are isolated fixtures. The real CLI advisor and driver
are exercised; no live pane, tracker/provider call, updater or cycle executor
is used. The fresh-session record is explicitly simulated, not a live relaunch
receipt. Installed acceptance requires that separate receipt.
