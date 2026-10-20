# Seed before scheduled agent assignment

`shantytown.scheduled_seed` is a source-only library for an already admitted
scheduled agent firing. It starts no listener, timer, shell or background work.
The runtime owner supplies the immutable job policy and exact signed-run IRI.
`SeedRequest` validates the existing canonical Chaski run encoding against the
job and UTC slot. Parsing an identity does not authenticate a delivery or grant
executable admission.

The stable external reference is `scheduled-agent-v1-` plus SHA256 of canonical
JSON containing the job IRI and integer scheduled slot. It survives recipe or
revision changes. The ledger separately binds the complete request and proven
store identity, so a changed policy for that slot refuses rather than creating
a second task. No ontology namespace is changed or inferred. The signed-run IRI
must use the runtime's admitted immutable Shuttle entity namespace.

`NativeSeedPort` uses the existing `SdTracker` store proof and native
`--workflow-run RUN --step agent-task --visit 1` keyed create. The seed is OPEN
and unassigned. It carries the stable external reference, completion due time,
job in its description and native `workflow_run` reference to the actual run.
That existing SDK relation makes the run's seed queryable in reverse; this code
adds no shape, type or parallel vocabulary. The exact job/firing producer profile
and graph views still belong in the domain factory.

After creation, exact raw readback must verify identity, title, description,
external reference, workflow run, due time and OPEN/unassigned state. Only then
does the local ledger claim the assignment call. The port calls the trusted
normal ST command seam with `go SEED RECIPIENT --quipu-node JOB`, preserving its
governor, triage, assignment and journal path. For example, a runtime adapter can
wrap `cli.main([*PINNED_ROOT_BACKEND_REGISTRY_ARGS, *argv])`. Nothing in incoming
data selects that command implementation or deployment routing. A callback's
return is not proof of a governed production delivery unless it is this admitted
normal path and its actual readback.

## Uncertainty and replay

A dedicated owned SQLite ledger commits `creating` before the native request.
An exception, timeout, malformed receipt or unverifiable readback leaves UNKNOWN:
no second create and no assignment. A callback returning an ID is insufficient.
The native keyed-create API is a second idempotency control for the same run and
step; it does not authorize retrying an uncertain request.

The owner can supply the exact existing seed ID to `reconcile_created`, which
requires the same scoped raw readback and only changes the local `creating`
claim to `seeded`. It performs no create or assignment. Normal delivery may then
make its one assignment call. This is not an automatic title search or board
scan. Concurrent reconciliation cannot overwrite an existing assignment claim.

The ledger commits `assigning` before normal `go`. Exit zero records delivered;
explicit refusal records refused and retains the visible seed. Neither repeats
the call on replay. An exception, invalid return or exit two retains UNKNOWN,
including a potentially delivered request whose reply was lost. There is no
automatic assignment replay or silent reassignment. The agent closes the seed
with its result; closure and overdue/missed-deadline observation remain normal
board/domain responsibilities.

Keep the execution ledger, seed and existing signed-run/outbox state across
restart and rollback. Do not point this ledger at a board database, delete it to
retry work or reuse it for a different store. Existing unrelated tables,
symlinks, hard links and unowned/writable ledger paths refuse. This is ordinary
SQLite durability, not isolation from another process with the same uid or a
cross-service atomic transaction. A lost ledger is not permission to execute.

`for_code_outcome` validates the actual trusted process outcome and creates work
only on failure. Successful and held pure-code runs make no seed here. Shuttle
still owns their signed run records and publication; this library does not
substitute seed creation for run recording.

## Source proof and remaining integration

Run `SCHEDULE_TEST_SD_BIN="$(command -v sd)" python3 docs/demos/scheduled-seeds.py`.
The demo creates an explicitly temporary local SDK project/store with an isolated
HOME, CWD and identity. It exercises real keyed create/readback, replay after a
ledger reopen, a simulated lost response after an actual local commit, exact-ID
reconciliation and pure-code success. The assignment callback is explicitly
synthetic: no real pane, production queue/store or signing credential is used.
The optional native SDK test uses the same isolation; ordinary CI reports that
one test skipped if the explicit SDK executable is unavailable.

The source library is not yet wired into Chaski's fixed executor or a production
domain profile. The runtime compiler must bind the admitted canonical slot/run
metadata, immutable policy, source environment and normal ST command seam.
Keep calendar semantics, per-run episode and per-finding nodes, installed
signed publication/readback, deadline drill and rollback gates. Root's concrete
deployment ACK/current CI are required before enrollment. No service, key,
schedule or cron state changes through import or these fixture probes.
