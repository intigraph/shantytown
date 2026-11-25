# Verified-wake recruitment adapter

`shantytown.recruit_adapter.ReviewAdapter` is the source entrypoint joining the
existing verified-inbox drain to native item/readiness admission and the signed
controller endpoint. It adds no listener, service, sudo rule, installer, live
report hook or activation flag. Merge is permitted; runtime adoption remains a
separate operator action. The production launch flag stays OFF.

A trusted host composition supplies the existing native tracker, forge reader,
Quipu reader factory and current policy, plus an explicit bounded mapping from
repository/PR to item ID. That mapping is a lookup hint: neither it nor an event,
PR body, branch or comment establishes custody. Every admission reads the exact
native item and parses its existing `chaski.github.work-request/v1` record.
Missing, mismatched or incomplete authority refuses.

The consumer supplies its existing candidate data class, keeping Shantytown free
of a Camayoc runtime dependency. For example, a reviewed composition can supply
Camayoc's `Candidate` and pass the three bound methods to its verified drain:

```python
adapter = ReviewAdapter(
    root=root, host=host, policy=policy, tracker=native_tracker,
    items=configured_item_routes, candidate=Candidate,
    gh=native_forge_reader, quipu=native_quipu_factory,
    private_key=configured_private_seed_path,
)
drain_once(
    verified_spool, repos=protected_repository_allowlist,
    resolve_ready=adapter.resolve_ready, admit=adapter.admit, spawn=adapter.spawn,
)
```

The caller retains the drain's durable candidate reservation and terminal
unknown/refusal semantics. It must not invoke these callbacks as an automatic
retry path or treat a prior readiness result as a lease. Policy/configuration
and collaborators are trusted host inputs, never fields accepted from a wake.

The requester must match its protected principal/UID/host/root/repository scope
and the protected controller public binding. The adapter accepts review launch
only. It rechecks native custody before reading a private0400 single-link seed
through pinned private directory FDs. The public half must match the protected
binding. A fresh nonce and at most60-second lease are signed; scope/binding is
read again before the existing protected endpoint exchange.

Only a controller receipt for the exact signed operation hash, exact head and
review-job name can be retained as the confirmed spawn result. Prepared,
refused, malformed, wrong-operation or lost replies never become success or an
automatic retry. The response grants no independent launch authority. Native
controller signature, nonce, planner, identity, holds, cap and final authority
checks still apply; the adapter introduces no administrator identity.

## Qualification and remaining runtime gates

Focused tests cover default-OFF before IO, exact native custody, requester/route
mismatches, malformed/ambiguous wakes, private-key ownership/mode/link/public-pin
controls, changed binding, invalid receipt and lost-response handling. Native
tracker and fixed-file tracker implementations retain their existing exact-ID
protocol; the adapter does not implement a new Seeds wire API.

The deployment's loopback HTTP/test-socket composition additionally exercises
this module with the reviewed receiver, signatures, durable ledgers and native
spawn admission. Its terminal job launcher and enrollment are explicit fixtures:
modeled requester UID10001 is not a kernel UID-drop proof. No production key,
root listener, sudo or real job is used. HTTP totals must include native item
lookups, verdict/author reads and every controller recheck; counting one callback
as one request understates that budget. Production Seeds transport amplification
must be measured separately before claiming a deployed budget.

A production host entrypoint, verified controller identity, protected endpoint
installation and activation require separate operator approval. Reverting this
module removes its source callbacks; it never deletes nonce/attempt tombstones,
undoes a remote job or licenses replay of an unknown result.
