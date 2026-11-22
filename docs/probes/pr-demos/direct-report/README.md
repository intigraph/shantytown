Run `python3 docs/probes/pr-demos/direct-report/demo.py` with `codex` available.

This offline probe renders the same synthetic task job on base `6fc8c2ff` and
the candidate source. Watch the report instruction change from stdin to a
direct command with one quoted, nonempty summary. The existing native policy
allows that direct command, has no match for the shell/heredoc wrapper, and
still forbids a push. No sandbox root or report permission changes.

Replay `output.log` with `scriptreplay --log-timing timing.txt --log-out output.log`.
The recording demonstrates prompts and policy matching only; it launches no
job, writes no report, and does not prove installed live acceptance. Regression
tests separately show empty summaries refused before verdict or terminal writes.
