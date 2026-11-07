# Automatic work refill

The fleet-owner `st fleet tend` sweep sends unassigned ready work through normal
`st go` dispatch when an observed feedable worker or lead has no workable owned
queue. A plate containing only externally blocked work can receive another
eligible item. Existing owned ready or active work stays with the haul path.

Selection uses declared priority and rank. Exact tracker reads, current hold,
governor, capacity, runtime, ownership and delivery checks still decide each
dispatch. Claude may author ordinary work; design and important Quipu-code labels
express preferences. Reviews remain Codex-only. The ranker appends preference
labels to declared design and Quipu-code work without replacing other labels.

Only the existing fleet-owner sweep performs refill. Known local capacity can
continue when a peer census fails, but coverage is reported as unknown. No new
daemon, schedule or peer feeder is started.

## Uncertain outcomes

`refill/state.json` reserves a worker and item before a dispatch. An indeterminate
result retains that reservation across ticks; another worker cannot receive the
same item. The ordinary tracker, delivery custody and turn receipts must be
reconciled before an operator resolves that reservation. Time alone never
authorizes another send. `refill/observations.jsonl` retains natural observations.

### Reconcile a recorded Codex delivery

When an operator has proved that an uncertain dispatch reached the recipient,
the installed module can qualify that existing receipt without another send:

```sh
python -m shantytown.refill_reconcile --root /path/to/deployment --receipt receipt.json
# Only after the read-only result is qualified:
python -m shantytown.refill_reconcile --root /path/to/deployment --receipt receipt.json --apply
```

Use the deployment's normally installed interpreter and source. This is an
explicit reconciliation operation, not a new scheduler or a forced tend tick.
Native metadata and the target receipt remain limited to 2 MiB each. Unrelated
preceding events are skipped in bounded chunks, preserving physical line numbers;
the archive and traversal remain limited to 256 MiB.

The receipt is a JSON object with exactly these fields:

```json
{
  "version": 1,
  "worker": "worker",
  "item": "work-1",
  "pending_at": 1000,
  "custody": "send-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "history": "rollout-session-id.jsonl",
  "line": 2,
  "event_sha256": "SHA256_OF_THE_COMPLETE_ORIGINAL_JSONL_LINE_INCLUDING_NEWLINE"
}
```

The operator reads these values from the existing reservation, delivery custody
and normal archived harness history. The example hash is a placeholder, not an
admissible receipt. The module reads only `history/<worker>/<history>` beneath
that deployment. It binds the card's Codex harness, pane and workspace, native
session ID, exact dispatch item and serve footer, reservation/send/receive times,
and the complete accepted **user** message. A quotation, compaction summary,
assistant message, wrong hash, conflicting audit or changed reservation refuses.
Other harnesses have no implicit compatibility fallback.

Apply takes the existing refill lock followed by the normal composer-custody
lock. It durably appends a prepared audit with the original UNKNOWN custody and
reservation before recording the proven delivery and removing only its matching
reservation. `refill/reconciliations.jsonl` remains append-only. The original
observation journal and other workers' reservations remain unchanged. Repeating
the same receipt is idempotent; an interrupted operation resumes only against
its matching prepared audit and original evidence. It never clears a new
reservation for the same worker. A truncated audit refuses rather than resetting.

Reconciliation does not change observation timestamps, coverage, errors or
waiting records, and cannot certify scheduled health. Retain the source revision,
receipt, audit and rollback. After normal source qualification and installation,
read back the exact reconciliation, then observe the original scheduled publisher
and tend cadence for pending count and known coverage. A surviving read error
keeps coverage unknown. Do not manufacture a new acceptance epoch or invoke a
tick to clear it. Rollback reverts source through the normal lane and preserves
the audit and proven delivered state; it does not re-add a delivered reservation
or replay its message.

The existing changed-digest administrator alert reports unknown coverage,
refused or uncertain dispatches, exhausted observation budgets and owned queues
that remain idle for 15 minutes. It does not repeatedly type the same alert.

Composer recovery runs locally before optional board observations. It clears
only an exact retained failed/superseded machine body in its original known
Codex session, while idle. Every editing key rechecks ownership and framing.
Foreign drafts, busy panes, mismatched sessions and ambiguous custody stay
untouched. Clearing text does not acknowledge an alert or submit a message.

Explicit `st fleet tend --unretire NAME` can find an already-retired identity.
It retracts only the exact `crewStatus` literal and verifies the restored role,
host and reporting relationship. It does not create, reparent or launch an
identity as part of restoration. Ordinary registry reads still exclude retired
members.

## Scheduled acceptance

The existing governor publisher exports `st_refill_observation_known`, the last
observation timestamp, pending count and age, and
`st_refill_owned_queue_idle_seconds`. The last metric measures observed idleness
with an owned queue; it does **not** assert that a governor admits that work.
Missing, stale or incomplete observations are unknown, never a zero-idle proof.

After installation, retain the executing revision, rollback revision, original
tend cadence and first successful scheduled observation. Verify one ordinary
dispatch and one unchanged alert-dedup tick, then keep acceptance open for a
continuous 24 hours. Inspect the observation journal and normal dispatch audit:
each observed idle member with an eligible candidate must receive normal dispatch
within 15 minutes; investigate any eligible interval over 30 minutes. Join
owned-queue waits to haul/governor evidence before calling them eligible.
Unknown intervals or absent peers cannot satisfy the all-crew acceptance claim.
Do not backfill, reset an epoch or invoke a synthetic tick to certify the window.

Rollback is an ordinary source revert followed by normal projection. Preserve
pending dispatch custody and the journal across rollback.
