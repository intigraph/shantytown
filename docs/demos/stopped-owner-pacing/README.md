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
