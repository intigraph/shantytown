# Receipt-bound refill reconciliation

The same private file fixture starts with an uncertain, already-delivered
dispatch and one reserved worker. Read-only qualification retains the
reservation. A wrong event hash refuses. The exact native user receipt releases
only that reservation, retains the original `PartialAnswer`, and records the
original UNKNOWN custody in the audit. Repeating the receipt is idempotent.
A separate ordinary-observation fixture then reports known coverage.

This is source behavior, not installed or naturally scheduled acceptance.
No tracker, network, real harness, production state or scheduler is invoked.

- Base: `fa4d7e08e1ae25c9da160553b463afeb99a1baa2`, whose existing uncertain-send
  behavior retains the reservation and has no reconciliation entrypoint.
- Behavior source: `03a38ec52819ca8062f75fd093bce186577336ea`. The later demo
  assets commit changes no behavior source or tests.
- Reproduce from the repository root: `PYTHONPATH=. python3 docs/demos/refill-reconcile/probe.py`.
- [Readable transcript](transcript.txt), [raw terminal recording as text JSON](recording.json),
  and [original timing](timing.log).

The original 699-byte terminal output, including its CRLF bytes and recorder
metadata, has SHA256
`b7e819cf060e29df501d9495dff3ebd18cc32e779f0b6c34945d99a5f36991fc`.
JSON escaping keeps the recording a plain-text proposal while preserving its
exact bytes. Round-trip decoding and actual timed playback were checked against
the readable transcript. The recording and its reproduction both completed
under the HOME guard without changing watched resources.

Download the JSON and timing file, then replay with util-linux `scriptreplay`:

```sh
python3 -c 'import json,sys; sys.stdout.buffer.write(json.load(open("docs/demos/refill-reconcile/recording.json"))["output"].encode())' > /tmp/refill-reconcile-output.log
scriptreplay --log-out /tmp/refill-reconcile-output.log --log-timing docs/demos/refill-reconcile/timing.log
```

These small, sanitized assets remain in the repository with this demonstration.
There is no inline-video claim or external upload.
