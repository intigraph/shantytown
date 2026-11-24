# Offline post-deploy watch template

This template evaluates bounded local evidence using the same `WatchSpec`
validator for JSON and TOML. It has no network collector, credential, managed
unit, Action executor, scheduler or job launcher. Its output explicitly says
`OFFLINE_UNAUTHENTICATED`; it is not a signed result or deployment permission.

From the repository root:

```sh
python3 -m shantytown.watch_replay --spec docs/examples/watch/watch.toml --evidence docs/examples/watch/inactive.json
python3 -m shantytown.watch_replay --spec docs/examples/watch/watch.json --evidence docs/examples/watch/breach.json
```

The first returns exit 0 with safety PASS, activation INACTIVE, improvement
NOT_EVALUATED and compensation NOT_EXECUTED. The second returns exit 1 with
BREACH. Exit 2 means malformed or refused input. Other non-PASS safety results
also return exit 1. No exit status authorizes close, rollback or activation.

These are synthetic fixtures. Bounds, timestamps, identities and receipts must
be selected through the deployment's admitted controller before a real watch.
The evidence envelope binds the exact run/source/receipt; every sample also
carries the frozen deployment identity. `now` and activation are fixture input,
not authenticated clock or native-probe evidence. The bounded local adapter
cannot establish freshness, provenance or source authority.

The end sample is included even when cadence does not divide the window. A
valid partial prefix reports its next original sample time; a gap or reordered
prefix has no resume cursor. Replaying evidence never resets the start time.
JSON duplicate keys, non-finite constants, unknown fields, files over 4 MiB,
symlinks and non-regular inputs refuse. Both source formats call one validator.

The runtime integration still needs an admitted source/reader, managed-unit
custody, authenticated clock and activation probes, durable signed callback,
and the common pre-approved revert Action plus breach-only triage job. This
adapter accepts no executable command and cannot bypass those gates. Two real
pane-free watches remain the parent acceptance requirement.
