# Shared reminder transport

`overdue_ports.bind(args, panes)` supplies the same selected tracker, registry,
durable inbox sender and exact receipt reader to fleet reminders and finite
`unlock_reader.react` callers. It adds no schedule or notification policy.
The existing `notify/overdue.json` and `overdue.lock` remain authoritative.

A returned message identifier is confirmed only after an exact recipient, marker
and identifier read. Native message receipts include read messages and all
registered windows. Missing metadata, duplicate identifiers and capped reads are
UNKNOWN. Legacy identifiers continue through the legacy exact reader.

If delivery returned an identifier but the read fails, `PendingReceipt` retains
that original identifier. The shared reminder ledger owns subsequent receipt
reconciliation and prevents another send. Delivery confirmation does not prove
review completion or a producer ACK. Callers requiring a terminal result must
also verify their producer and ACK outcomes; an empty sweep result alone cannot
prove success because the reminder consumer retains errors and busy locks.

This source interface does not admit a controller profile, enroll an identity,
change credentials, or enable external unlocks. Runtime bindings need their own
scope, immutable artifacts, receiver result descriptor, resource limits and
paired disable/drain acceptance.
