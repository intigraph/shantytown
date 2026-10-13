# Read attribution at tracker boundaries

Read metadata is diagnostic declaration, never an authenticated identity, write
actor, PID ownership claim or authorization. The client category stays `seeds`.

The native plate HTTP reader and read-only SDK subprocesses preserve explicit
`QUIPU_AGENT`, `QUIPU_TASK` and `QUIPU_SESSION`. Legacy declared `SEEDS_AGENT_NAME`,
`SEEDS_TASK` and `SEEDS_SESSION` fill missing fields. `SHANTY_AGENT` supplies crew
identity only inside a declared Codex/Claude harness. Missing crew context stays
missing; an item owner, CLI actor or component name never supplies that context.
No supervisor environment is changed: subprocess metadata is a child-only copy,
and nested scopes restore on exceptions.

`st-tend` is a component source, separate from the reader declaration.
`X-Quipu-Source` identifies that component or `shantytown`;
`X-Quipu-Operation` identifies finite projection names such as `ready-count`,
`owner-rows` and `uses-native-schema`, or the SDK read verb. Explicit source and
operation declarations retain precedence. They use bounded token syntax and
carry no query text or command arguments. These extension headers create no
per-request metric labels. Servers that do not expose them cannot yet join a
completion to the declared operation; sent headers alone do not prove visibility.

Coverage: `SdTracker.prove_store`, its `show/list/ready/where/search/count/info/stats`
children, and all native plate projection requests. Write commands retain
legacy provenance, actor flags and authentication behavior. Direct `sd` requests
need the SDK read-attribution counterpart before missing caller metadata ceases
to name its producer `seeds`. Other shell wrappers and SDK entry points outside
these boundaries are not certified by these tests. Stale process environments
are not repaired, and no new collector or accounting window is introduced.

Transport controls use real loopback HTTP and child processes, preserve task,
session, explicit identity, ASK/count/plate semantics and parent environment.
The frozen fleet rate remains independent: diagnostic attribution alone does
not reduce aggregate traffic or satisfy a query-rate target.
