# Delayed soft clear

An idle-looking pane can resume a turn after a Stop hook blocks it. The actual
base verifier accepts changed chrome without a token footer and reports success
before a queued clear executes. The candidate refuses that observation, retains
the request and sends only one clear across retries. A fresh hook session ID and
transcript path then prove the delayed clear.

Run `python3 docs/demos/soft-cycle-receipt/probe.py` from the repository root under
the HOME guard. The probe extracts and executes the actual base and candidate
verifier functions against disposable hook files and an inert pane. It does not
invoke a live cycle, start or kill any runtime, or prove installed recovery.

Download output.txt and timing.txt and replay with:
`scriptreplay --log-out output.txt --log-timing timing.txt --divisor 100`.
The recording prints the exact baseline. The sender source is the implementation
commit preceding this caption. Runtime projection and a naturally requested
cycle remain separate acceptance gates.

Rollback is a normal source revert and projection. Retain any pending clear
intent and checkpoint; do not remove it or repeat a clear to force success. An
already queued clear may execute later, so reverting does not cancel it.
