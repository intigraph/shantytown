# Typed evidence observation capacity

Synthetic fixture: fifteen held ruling/activation conditions, twelve evidence
reads per pass, and two prior failures per condition. No grants, network calls,
production state, or release operations are used.

The same probe on base `fa4d7e08e1ae25c9da160553b463afeb99a1baa2` and source
`3562ccbfedd1f9109a419f8b9adc0a47fe5b79ac` shows:

| Observation | Before | After |
| --- | --- | --- |
| Reads per pass | 12 | 12 |
| Unobserved conditions' prior count | 2 → 3 | 2 → 2 |
| First-pass administrator alerts | 1 | 0 |
| Distinct conditions read over four passes | 12/15 | 15/15 |
| Conditions released | 0 | 0 |

The [output recording](output.log) and [timing file](timing.log) are small,
retained repository artifacts. Replay with util-linux `scriptreplay`:

```sh
scriptreplay --log-out docs/pr-demos/typed-gate-budget/output.log \
  --log-timing docs/pr-demos/typed-gate-budget/timing.log
```

Regenerate from a full clone containing the baseline:

```sh
python3 -B docs/pr-demos/typed-gate-budget/record.py
```

The candidate identifies itself with the current checkout SHA. The recording
uses the source commit above; later recording/docs commits preserve its runtime
blobs. This is a source-fixture demonstration, not installed acceptance. Genuine
read failures must still produce their three-pass alert; the regression suite
checks that separately, including private-error-text redaction.
