# Dependency priority around admitted operations

A P0 dependency wait previously changed a planned or in-flight operation from P2
to P0. That unrelated revision could invalidate the operation's BEGIN binding.
The candidate preserves the operation's priority while retaining the wait.
Ordinary dependencies still inherit P0.

This is an offline library demonstration, not an installed-service test.
`demo.py` compares committed base `f909de3e3ba445946545dd673f94edea1de2d0fd`
with the candidate `gate_backstop.py` shipped beside it, using identical inputs.
The real Dispatcher/tracker regression is in `tests/test_gate_backstop.py`.

Run from the repository root:

```sh
python3 docs/probes/admitted-gate-priority/demo.py
scriptreplay --log-out docs/probes/admitted-gate-priority/output.log --log-timing docs/probes/admitted-gate-priority/timing.log
```

[Output transcript](output.log) and [timing](timing.log) form a short terminal
recording retained with this source. Download both for terminal replay; inline
playback is not promised. The three observed decisions are ordinary `0 -> 0`,
planned `0 -> 2`, and in-flight `0 -> 2`. No network or tracker writes occur.
