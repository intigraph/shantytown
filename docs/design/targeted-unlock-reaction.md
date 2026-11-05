# Targeted external-blocker reaction seam

A matching reaction can call `shantytown.unlock_reader.react` with an exact
seed ID, the selected Seeds tracker, the crew registry and the existing shared
inbox delivery and receipt adapters. This is a library seam, not an installed
reaction, scheduler or new notification sender.

The selected Seeds CLI must support `blockers reconcile <id>` and
`blockers events <id>`. Unsupported syntax fails without an unscoped retry.
The native producer rechecks all conditions and internal dependencies before
opening a feature-managed blocked seed and persisting its unlock generation.
The shared notifier uses its existing receipt/ACK ledger and lock. A replay
cannot authorize another delivery; uncertain reconciliation and delivery remain
fenced. Unrelated pending packets, retained entries and ACKs stay unchanged.
An unrelated pending packet for the same recipient holds the targeted notice
until the regular shared consumer reconciles it.

This callback performs no due-board read. No caller should run a full fleet
sweep to invoke it. The deployment still needs a reviewed matching-reaction
binding, selected store/graph, existing delivery authority and disable contract.
Keep the external-unlock configuration off until that runtime binding is
admitted and tested with a real unresolved/resolved foreign node and a retained
notification receipt. Source tests alone do not prove installed delivery.

Focused verification:

```sh
python -m pytest -q tests/test_unlock_reader.py tests/test_overdue.py
```
