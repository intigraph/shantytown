# Roster status guard: fixed-store comparison

The roster guard must reject an owned Action with missing or unsupported status.
Previously its owner/type filters performed type checks for ordinary known-state
rows. The candidate first selects unsupported states, then joins roster owners.
The missing-plain-status branch retains a separate typed relation so Quipu can
use its indexed absence path. Single-owner queries retain the previous form.

This is a transcript of an isolated native fixture, not an installed-service
measurement. A terminal recording was unavailable (`asciinema` is not installed).
Base source: `6bccc8d7f1f502e12daba586d8fb6e47002924b4`; the candidate is the
guard change in this PR. Runtime: clean Quipu 0.17.0,
`f3982337b2211a28b8cf465faebad23ca51b28ee`.

The retained profile transcript compares the old existential guard with the
candidate on one unchanged store containing 5,000 ordinary closed Actions,
one unknown-status Action and one missing-status Action. Both return exactly
the same two refusal subjects. Inclusive profile timings are not additive and
one timing sample does not establish a latency percentile.

```
old: rows=[urn:unknown, urn:missing], BGP calls=15010, elapsed_us=226009
new: rows=[urn:unknown, urn:missing], BGP calls=7, elapsed_us=8784
```

Repeat the committed smaller regression fixture:

```sh
SHANTYTOWN_TEST_QUIPU_SERVER="$(command -v quipu-server)" \
  python3 -m pytest -q -s tests/test_seeds_owner_guard_native.py
```

It compares result bags on both graphs, including missing, unknown, nonplain
and mixed statuses, owner aliases and duplicates, and cross-graph controls.
It then adds 500 ordinary closed Actions and requires at least five times fewer
native BGP evaluations with the same refusal bag. Running that assertion with
the old query restored fails with `[1670, 1670]`; a result-only check would miss
the original performance bug. Absolute counts can change with the engine.

This small text artifact is retained in Git alongside the regression. It does
not demonstrate production timeout recovery, display-consumer activation or
the separate whole-board summary work.
