# Technical gate and stalled chain

Replayable terminal recording: [output.log](output.log), [timing.log](timing.log).
Run `scriptreplay --log-out output.log --log-timing timing.log` from this directory.

The same private fixture calls the real Dispatcher and DeferralAlerter. Before (base 28a4f7fc7965acc13978b6384ef434fc7d3ccdaf), an unreasoned gate is accepted and the exact paper → deferred release chain produces zero events across two passes. In this proposal, the gate is refused and the chain produces exactly one event across two passes. The target's explicit deferred state is the positive control. All items, notification delivery and ledger storage are disposable fixtures; this proves source behavior, not an installed tend pass.

Reproduce with `python3 docs/probes/pr-demos/gate-backstop/probe.py CHECKOUT` from the repository root. For both versions, extract the base's shantytown package to a temporary directory with git archive, set GATE_DEMO_BASE to that directory, and run `bash docs/probes/pr-demos/gate-backstop/record.sh`. Recording and small text artifacts are retained in the existing repository demo directory. This proposal's eventual commit identifies the candidate source; changes to source require the same probe to be rerun.
