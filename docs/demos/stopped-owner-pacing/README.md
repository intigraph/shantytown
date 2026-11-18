# Stopped-owner pacing

The actual deferral alerter processes the same 85 private synthetic rows before
and after the change. A valid deliberate-stop record exists; the lead is live.
All board reads and notification transports are fixtures. No service, crew
runtime or live item is modified.

The baseline is main `69939c843951b9199c57c696532b6c55db7d7681`. The probe
prints the observed routing-source SHA256, delivery counts, retained held rows
and counts after a repeated sweep. The candidate produces one administrator
digest instead of 85 lead wakes, without un-deferring or reassigning the rows.

Set `PACING_BEFORE_SOURCE` and `PACING_AFTER_SOURCE` to explicit source trees,
and `PACING_PYTHON` to an interpreter containing pytest. Run `run.sh` under the
HOME-escape guard. `output.log` and `timing.log` are a terminal recording;
replay with `scriptreplay --timing timing.log --log-out output.log`.

The recording proves fixture routing and repeat suppression. Installed and
natural fleet acceptance remain separate.

## Release-eligible follow-up

The original probe held `can_release` false. It did not exercise an ordinary
lapsed date that the automatic release loop would accept. The follow-up probe
uses the real evaluator and release decision, two P4 rows, and private board,
stop-marker and notification fixtures.

[Actual transcript](release-eligible-output.txt): base `6b8ab7df` releases both
rows before batching (zero digests); the candidate retains both and sends one
administrator digest, suppresses the repeated batch, and resumes ordinary release
when the deliberate-stop marker is cleared. No live service is exercised.

Repeat with an interpreter containing pytest:

```sh
python docs/demos/stopped-owner-pacing/release-eligible.py /path/to/source
```

The transcript is unedited stdout from the same probe against base and candidate;
it has no timing track. The candidate behavior is bound to `notify.py` SHA256
`b168608af60eefe53905ef3f83b4f53e4831151b34bb81a0fb7566ea9b29660e`.
Installed and scheduled acceptance remain separate.
