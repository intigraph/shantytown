# Technical gate and stalled chain

Replayable terminal recording: [output.log.gz](output.log.gz), [readable transcript](transcript.txt), [timing.log](timing.log).
Run `gzip -dc output.log.gz > replay.log` then `scriptreplay --log-out replay.log --log-timing timing.log` from this directory. Raw recorder bytes and timing are preserved; the text transcript only normalizes terminal CRLF.

The same private fixture calls the real Dispatcher and DeferralAlerter. Before (base 28a4f7fc7965acc13978b6384ef434fc7d3ccdaf), an unreasoned gate is accepted and the exact paper → deferred release chain produces zero events across two passes. In this proposal, the gate is refused and the chain produces exactly one event across two passes. The target's explicit deferred state is the positive control. All items, notification delivery and ledger storage are disposable fixtures; this proves source behavior, not an installed tend pass.

Reproduce with `python3 docs/probes/pr-demos/gate-backstop/probe.py CHECKOUT` from the repository root. For both versions, extract the base's shantytown package to a temporary directory with git archive, set GATE_DEMO_BASE to that directory, and run `bash docs/probes/pr-demos/gate-backstop/record.sh`. Recording and small text artifacts are retained in the existing repository demo directory. This proposal's eventual commit identifies the candidate source; changes to source require the same probe to be rerun.

Status-only blocked waiter review correction

The same fully known target and waiter metadata are used on base `aaeecc697d68e2a7217186aadeb15c1942af4b4b` and demonstrated source `3d9158c95cbbb8f3fd8ac4ebd69baf8fbbdcd756`. The deferred positive control emits one event in both; the status-only blocked waiter changes from zero to one event. This is a private-data-free library fixture, not installed acceptance. [Recording output](blocked-output.log.gz), [timing](blocked-timing.log), and [repeat command](blocked-record.sh) retain the actual before/after run. Replay with `scriptreplay --log-out <(gzip -dc blocked-output.log.gz) --log-timing blocked-timing.log`; playback verified. Subsequent recording commits leave demonstrated runtime behavior unchanged.
