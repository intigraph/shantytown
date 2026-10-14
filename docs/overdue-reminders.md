# Overdue and unlock reminders

Enable the reminder sweep in the deployment's reviewed configuration:

```toml
[overdue]
enabled = true
external_unlocks = false # opt in separately after the Seeds producer is installed
```

It runs within the existing `fleet tend` schedule, host-owner admission and
sweep budget. Dry-run tend does not send reminders. Other deployments remain
unchanged until enabled. The reader selects active due-bearing item fields,
not descriptions or retained import blobs, and refuses incomplete results.

Each recipient receives one digest for newly overdue work, followed by at most
one daily reminder for unchanged overdue episodes. Assigned items go to their
assignee; unassigned items go to the declared administrator. Unknown owners are
reported as unknown. Inbox pointers are excluded. Closing or re-dating an item
ends its overdue episode. The visible preview is bounded; the intent packet
retains complete membership in `notify/overdue.json`.

Delivery intent is persisted before sending. Stable inbox receipt markers
reconcile an indeterminate write without a second message. An absent receipt
never permits a resend after the persisted attempt fence; unknown attempts remain
pending for operator reconciliation. Unreadable board
results, corrupt ledgers and unknown receipts cannot authorize duplicate sends.
Overlapping passes hold one lock. A reminder asks the owner to close, re-rank,
or re-date with a reason; it does not change an item's state or bypass a gate.

## Shared unlock event input

`OverdueAlerter(..., events=reader, receipt=lookup, deliver=sender)` also consumes
an exact `Answer` of persistent readiness events:

```json
{"kind":"unlock","id":"example-1","episode":"generation-2","recipient":null}
```

The blocker producer owns condition evaluation and stable readiness generations.
The shared notifier owns routing, digesting, delivery, receipt reconciliation and
schedule. A null recipient uses the administrator. Unlock episodes send once,
not daily. Their receipts survive temporary event absence, so replay of an old
generation cannot notify again. A changed generation constitutes a new event.
The producer must retain events across polling boundaries; an unknown condition
must never be promoted to readiness. The current external producer wiring is a
separate integration, not a second notifier or a delivery acceptance claim.

Tests exercise a 112-item digest, daily cooldown, explicit inbox exclusion,
re-dating, committed-but-unknown writes, restart reconciliation, event replay and
unassigned unlock routing. These are isolated fixtures. Closure requires an
observed run and actual receipt from the original schedule after normal source
projection, using an approved overdue control item.

With `external_unlocks=true`, the same admitted sweep reconciles the selected
Seeds producer before reading persistent pending events. An uncertain reconcile
write leaves a retained fence and does not repeat the write automatically.
Known overdue work can still notify when unlock evaluation is unknown. No
legacy/foreign backend is substituted.

The sender extracts the actual inbox receipt ID and verifies that exact item,
recipient, inbox label and marker. If the known-ID read is unknown, the intent
retains that ID for exact reconciliation instead of scanning all inbox history.
After verification, the consumer acknowledges the producer event with that
receipt. An uncertain ACK reads the exact retained event; a matching receipt
confirms it, a conflict refuses, and a readable null permits only the identical
ACK. It never permits another notification. Source flags, projection and joint
scheduled acceptance remain separate from these fixture controls.
