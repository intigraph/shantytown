# Completing a late Codex submission

A terminal send can remain unverified while Codex queues the message. A later
native `task_started` and exact `UserMessage` prove consumption, but do not
themselves authorize a dispatch. This change makes that proof available to the
existing explicit `st go ... --complete --receipt ...` path.

Reproduce without live keys, an agent process, or a tracker service:

```sh
python3 -m pytest -q tests/test_codex_native_submission.py
```

The integration fixture uses the actual terminal adapter's read-only observer,
an owned rollout, a current session binding and a file-backed tracker:

| Observation | Before late consumption | After explicit completion |
|---|---|---|
| Receipt | prepared, no submission or assignment | assigned, native user proof |
| Execution authorized | false | true |
| Send count | 1 | 1 |
| Tracker revision | 1 | 2 |

Repeating completion leaves the send count and revision unchanged. Read-only
reconciliation remains read-only and does not claim an item. Queue-only text,
tool output, different or ambiguous turns, a different thread, normalized text,
old timestamps, changed process/session/workspace and substituted rollout files
do not authorize completion.

The observer reads only the hook-bound rollout under the live process's
settings home. Its header must match the current stats session and card
workspace; input is bounded and file ownership is checked. Existing dispatch
scope, governor, uncertain-claim and supersession fences remain in force. A
superseded receipt cannot be revived by finding historical consumption.

This is a deterministic fixture transcript, not a recording or proof of a live
deployment. No terminal recording capability was available.
