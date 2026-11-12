# A lead on another host

The [actual before/after transcript](remote-lead.txt) compares base
`41bbe614d12057b582f70314cbb2e37fe2bff9dc` with implementation `c89cc924`.
A local worker names an administrator placed on another host, with no local
card for that administrator. The base refuses both anchor and stop routing.
The candidate resolves the remote identity, queues the stop to that administrator,
and selects the durable-relay seam. The local administrator receives no event,
and no local lead card is created.

Run the same fixture against each checkout:

```sh
PYTHONPATH=/path/to/checkout python3 docs/pr-demos/remote-lead.py
```

This uses temporary files, a graph stub, and a stubbed relay transport. It proves
the lookup and routing behavior, not fleet reachability, live drain wiring or
delivery. The tests also cover absent graph identities, missing local placement,
offline operation, and unavailable graph reads.

This artifact is a readable transcript, not a timed recording; `scriptreplay`
is unavailable on the recording host. The small sanitized transcript is retained
alongside the repeatable fixture in this existing demo directory.
