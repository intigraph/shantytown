# Bounded stale-work review

The existing fleet-owner tend ranking pass proposes a review of unowned
ordinary READY P3/P4 items whose modification metadata is at least 30 days old.
It reuses the existing bounded snapshot and changed-digest/hourly log cadence;
it performs no extra tracker query, close, defer, assignment or priority write.
Stale work alone never creates an administrator page.

This is a review proposal, not evidence that work is obsolete. Before proposing
closure or renewal, read the exact item, comments, dependents, due date and
current custody. Missing, malformed, future or timezone-free modification
timestamps remain UNKNOWN. Owned, active, held, ASK, inbox, permanent-anchor
and native-operation records are excluded. The underlying digest still has
its existing advisory scope and classification; the added review does not
change them. Inbox and deferred cull coverage remain unmeasured.

The demonstration runs the same isolated source-library report on base
`6bb4694988539c60fbc1a4060a9ecb75fe9c8bcf` and the candidate. The base ranking
module is byte-identical to the proposal base `895d653b26ca3a7a89016c6f9786b34d9dcc6c33`.
On the same fixture the old report has no stale-work review; the candidate
names one stale ordinary item while excluding ASK/native records and retaining
the no-page result. No installed acceptance is demonstrated.

```sh
HYGIENE_DEMO_BEFORE=/path/to/base-checkout python3 docs/demos/backlog-hygiene/demo.py
scriptreplay --log-out docs/demos/backlog-hygiene/output.log --log-timing docs/demos/backlog-hygiene/timing.log
```

The small output/timing pair is a terminal recording retained in this source
directory, with a readable transcript in `output.log`. Download both files for
local replay; no inline video playback is claimed.
