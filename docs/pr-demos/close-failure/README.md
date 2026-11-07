# Close refusal evidence

The controlled fixture runs the real `st work item close` CLI against a simulated
child refusal: an observe warning on stderr and the actual blocker in JSON on
stdout. It uses private temporary stores and performs no live tracker writes.

On baseline `834b8811c4ceafe8f58d425f384ee902590db369`, the CLI shows the warning,
hides the blocker, and labels the Seeds transport as `br`. On the candidate,
it retains the actual `sd` backend, child exit code, both redacted output channels
and the blocker. Both versions make one child call, return exit 2, and keep the
item open. This demonstrates reporting, not a bypass of the close refusal.

The [terminal recording](output.log) and [timing file](timing.log) can be replayed:

```sh
scriptreplay --log-out docs/pr-demos/close-failure/output.log \
  --log-timing docs/pr-demos/close-failure/timing.log
```

Regenerate from a full clone containing the baseline:

```sh
python3 -B docs/pr-demos/close-failure/record.py
```

The recording identifies the committed source SHA for each arm. Later recording
and documentation commits must preserve that candidate's runtime blobs. Installed
CLI acceptance remains separate from this source-fixture demonstration.
