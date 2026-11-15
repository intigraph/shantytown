# Crew memory across harnesses

The shared `CLAUDE.md` / `AGENTS.md` rulebook is separate from an agent's private
workspace memory. Codex does not discover Claude's project `memory/MEMORY.md`
through that rulebook link.

The existing SessionStart anchor bridges that memory into Codex context. It
resolves the runtime card's absolute workspace and effective harness, then reads
only the corresponding project index. For the legacy unnamed lane the source is
`~/.claude/projects/<encoded-workspace>/memory/MEMORY.md`. The workspace key uses
Claude's non-alphanumeric-to-hyphen spelling. A selected named account uses only
its existing account profile's `projects` directory; it never falls back to the
legacy profile or searches sibling accounts. Credential files are not read or
copied. Claude's own loading is unchanged.

This is a read-only bridge to the original file, not a second memory store or a
copy in `AGENTS.md`. It does not import sessions, enumerate unrelated projects,
or change the runtime card. The source path and loaded-text hash accompany the
notes. Historical notes require current verification and confer no new authority.

Startup output is bounded to 200 lines and 32 KiB of source text. A truncated
index explicitly warns that later directives may be omitted and points to the
original full index, which must be read before relying on the partial notes.
Unsafe, changing, invalid or unreadable memory reports UNKNOWN. A missing index
does not select another project's memory. The anchor still includes memory if a
tracker read fails; unknown tracker state remains unknown.

The existing emitted Codex SessionStart command exercises this path. Tests run
that command against isolated cards, memory and a file-backed fixture tracker;
they do not start or cycle a pane. A source test is not proof that an already
running session has loaded the change. Normal source review, CI and managed
arrival remain required before claiming installation.

## File transport for synchronization

The `shantytown.memory_files` library can snapshot a bounded, explicitly selected
memory directory and stage its exact UTF-8 bytes into a fresh generation. It
preserves the complete index and topic files; startup display limits do not
truncate stored source. It rejects links, non-regular entries, traversal, invalid
UTF-8 and exceeded limits. Secure descriptor operations are required; unsupported
filesystems refuse rather than use a weaker path-based fallback.

Staging never replaces an existing file, memory root, settings file or pointer.
An external edit after snapshot remains in the original root. Interrupted
generations remain unselected for inspection; rollback does not overwrite later
edits. A successful staged readback proves the new generation's bytes at that
point, not that a native harness has selected or read it. A verified harness
handoff and durable version synchronization are separate capabilities.

This library does not authenticate owners, ingest into Quipu, activate a memory
feature, or add memory CLI commands. Existing startup behavior and the original
memory files remain unchanged. Native generated stores must not be treated as
editable files without their own supported contract.

The versioned transport is a **Shantytown client feature** over ordinary Quipu
`POST /query` and `POST /update`. It adds no Quipu memory endpoint, credential
audience, listener or storage primitive. The existing administrator-owned named
CLI credential mapping selects the crew principal. The same normal Quipu bearer,
writer-scope policy, configured ontology and loaded shapes govern its writes.
Ambient/shared credentials cannot substitute for that selection. Public
cross-crew queries remain intentional reads, separate from own native staging.

Each exact deployment/project/crew tuple selects a deterministic named graph.
Ordinary `Artifact` records hold immutable JSON manifests and full canonical file
intents; labels, references and provenance remain ordinary RDF. `dcterms:hasPart`
links manifests to revisions; `rdfs:seeAlso` carries the collection head and
idempotency markers. A single conditional SPARQL update compares the expected
head, appends records and advances only the head pointer atomically in that graph.
It never deletes an old revision. The configured ontology must admit `Artifact`
and its required `reference`; unknown namespaces, loaded-shape refusals and writer
policy refusals remain failures. No shape set is installed by this feature.

The client first reads an exact idempotency receipt before checking a potentially
stale parent. A concurrent head change makes the atomic update match nothing;
a read-before-write check alone cannot authorize a write. A successful response
must include the expected one-graph transaction report, followed by exact intent
and receipt readback. Timeout or partial coverage preserves the outbox for later
readback and does not claim rollback. Export reads only the explicit owner graph
and the current manifest's bounded revision links, not an unbounded history scan.
Hashes, lengths, owner, paths, exact canonical request and revision IDs are
validated before staging. Startup display limits never truncate stored bytes.

`selected_owner` in the internal projection envelope records **local configured
routing**, not a server-authenticated memory identity or a per-owner server ACL.
The generic server's authenticated transaction provenance and writer permissions
remain the authority. A selected caller cannot request own operations for another
principal, and a changed mapping refuses before write/staging. Deployment must
qualify its normal graph writer/read boundary before enabling private uploads;
this client does not grant secrecy or a new identity capability.

Legacy Quipu memory records and their data are retained. The new graph format does
not silently import old primitive tables, rewrite old receipt IDs or adopt an
old remote head. Existing accepted-head journals therefore refuse a different
head; any migration needs an explicit reviewed mapping and content/count controls.
No runtime activation or private upload is implied by source installation.

The outbox library keeps immutable intents and verified receipts in an existing
private, user-owned directory. Each delivery reads the exact intent's receipt
before attempting at most one commit. Unknown outcomes preserve the intent;
there is no retry loop. A lost response can be reconciled on a later ordinary
trigger without another commit. A locally accepted delivery makes no network
request and does not rewrite the receipt or advance source-change freshness.
Corrupt, partial, linked or mismatched records refuse. The configured lifecycle and native adapter below use these libraries;
source support does not replace the installed startup bridge.

The explicit memory CLI can inspect source metadata, read manifests, query
attributed historical text or export a selected owner's bounded records.
Query scope is one explicitly selected owner/repository, not a global search
index. Own staging and writes retain their separate configured-owner requirement.
Frozen multi-file batches retain all exact intents before delivery, replay
accepted receipts before stale checks, stop on unknown/conflict and never
infer deletions from missing source files. A caller can bound delivery with
`max_new`: each pending intent consumes one allowance, including receipt-only
reconciliation after a lost reply; already accepted local receipts consume
none. An exhausted allowance returns `batch_partial` and a remaining count.
This bounds intent attempts, not elapsed time: each attempt may make one
receipt request and one commit, each subject to the client's timeout. These
transport primitives are not
yet an automatic lifecycle producer or native-root selector.

The synchronization library retains the accepted remote head and active frozen
batch in the same private outbox. A nonblocking lock serializes cooperating
triggers. An active batch resumes before source recapture; a new batch requires
the selected own remote head to equal the previously accepted head. Its
completion is accepted only after a fresh own projection proves the final
receipt head. Unknown outcomes and foreign heads retain the pending batch.
The small journal uses fsync and atomic replacement, and unchanged source does
not rewrite it. These guarantees assume cooperating processes on the same
secure filesystem; another writer with the same OS user can bypass the lock.
No automatic hook, native directory selection or remote-head adoption is
installed by this library.

The explicit `st agent memory <agent> sync` command now runs its synchronization
step in a disposable subprocess with a two-second elapsed budget, including
startup, followed by at most 250 ms of kill/reap cleanup. A timeout is UNKNOWN,
not success or evidence that a remote commit was rolled back. Source files,
frozen intents and the active batch remain for a later explicit invocation to
look up receipts before committing. The supervisor never retries. Its result
channel contains bounded metadata, with incidental worker diagnostics suppressed.
Other explicit transport commands retain their existing client timeouts.

The explicit `inspect` command uses a separate one-second disposable worker,
including startup, plus at most 250 ms of kill/reap cleanup. It returns metadata
for the complete bounded directory (up to 128 files); it never returns file
bodies or selects a native directory. A late, malformed or incomplete response
is UNKNOWN. The synchronization worker still uses its separate two-second
budget; these limits are not added to an unbounded in-process scan.

Each supervised worker holds only the read end of an exclusive parent-liveness
pipe. The parent holds the write end, which the operating system closes on
caller death. EOF stops the worker's own isolated process group. This does not
signal a crew session, service or unrelated PID, retry a request, or retract a
remote commit. The exact intent and receipt protocol still resolves unknown
outcomes on a later invocation. Direct worker invocation without this channel
refuses before doing work.

These budgets do not guarantee scheduling latency, termination of an
uninterruptible OS operation, or a fixed orphan-reaping latency. The explicit commands do not install a startup/stop hook or select a native
directory. The opt-in source wiring below still requires normal reviewed
installation and native acceptance before activation.

## Opt-in Claude lifecycle and native generations

Shantytown's source now supports a **disabled-by-default** per-crew plan in its
existing `shantytown.toml`. This example is synthetic configuration, not a
command to enable a running deployment:

```toml
[memory.alpha]
enabled = false
server = "https://knowledge.example.test"
deployment = "urn:example:deployment"
project = "urn:example:project"
account = "" # use the selected account; optionally pin its exact name/legacy
source = "/private/alpha/original-memory"
outbox = "/private/alpha/outbox"
staging = "/private/alpha/generations"
```

The administrator must select the crew member's actual existing native memory
root, not a directory inferred from a similarly named account. The source,
outbox and staging directories must already exist, be distinct and nonoverlapping;
outbox and staging must be private and user-owned. A named crew CLI credential
selection is mandatory. Its normal selected token is resolved through the existing
credential provider independently of the administrator's ambient token. The
server applies its normal writer authorization; own projection uses the local
configured owner and a validated ordinary graph manifest. An existing
credential refusal latch is never refreshed or bypassed by this path.

For an enabled Claude plan, normal managed launch preparation reconciles at
most one pending intent under the two-second worker budget. A partial batch keeps the current native root usable and reports pending;
ordinary bounded hooks resume its frozen intents before recapture. It does not
export a partial remote snapshot or claim native projection. Conflicts, unknown
identity, unavailable transport or unsafe settings refuse that launch promptly;
they do not silently select an older remote head. A
bounded refusal is not permission to retry, cycle a crew member or enable a
canary. The input settings must be regular, single-link, user-owned and not
group/world writable. Explicitly disabled auto memory, a different declared
native directory, or `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` refuses before ingest;
the plan does not override those native holds. Private outbox and staging
directories cannot be inside a Git checkout. Existing settings, hooks, permissions and environment are
copied into a new private artifact; the role's original artifact is untouched.

Only after selected-own projection agrees with the accepted head **and**
the current native source bytes does preparation create an exclusive generation.
It preserves complete UTF-8 index/topic bytes and relative links. It emits
Claude's documented `autoMemoryDirectory` and `autoMemoryEnabled` settings for
that future launch. The launch stamp records this exact prepared artifact.
Claude documents this memory-directory setting in its [memory reference](https://code.claude.com/docs/en/memory).
A synthetic settings consumer test is not an installed Claude acceptance receipt.

Preparation records a *pending* generation; it does not change the active source.
The actual SessionStart carrying that generation acknowledges it. An interrupted
preparation or failed launch therefore leaves the previous source authoritative
for the next synchronization. Stale starts and mismatched Stop sources refuse.
The same configured source and selected owner must match the journal.
Subscription account names are provenance, not another crew identity; an
optional account pin is enforced, and otherwise the actual selected account
is recorded. A verified same-crew account switch retains its accepted head
and generations without borrowing a sibling account profile. An
unchanged cycle reuses the generation and does not create another remote revision.

Claude SessionStart and Stop carry a bounded hook for configured crew only.
Other crew plans stay disabled, and a hook failure reports UNKNOWN while returning
success to the harness's own Stop decision. No daemon, timer or parallel hook
registry is created. Existing capture/stop hooks remain present. Codex's generated
memory writeback remains unsupported, so its existing read-only bridge and
ordinary launch are retained; OpenCode native writable memory remains unproven.
No alternate native path is fabricated for either harness.

The private liveness journal separates the last trigger/status, complete source
scan and observed content change, accepted ingest head/advance, and acknowledged
native generation/head/start. A trigger alone does not advance source-change or
ingest freshness. Resuming an active frozen batch explicitly reports that source
coverage was not rescanned. A killed worker may leave `running`, which is UNKNOWN,
never completed health. These are library/hook evidence fields; natural installed
trigger acceptance must still be observed.

No filesystem lock can exclude a noncooperating editor. A final source reread
refuses an observed edit during staging, but an edit **after** that check can
remain in an older retained root. No source file is overwritten or deleted; such
late edits require explicit reconciliation of the retained roots. The protocol
does not promise an atomic handoff against external editors, automatically merge
roots, infer tombstones, or silently adopt another writer's head. Deployment must
serialize managed launches and retain the prior native path and settings as the
rollback. Disabling the plan does not copy generated files back over that path.

Release, installed canary, authentic harness startup/read/write, cross-crew
queries, private archive migration and original-hook acceptance remain separate
reviewed deployment steps. Source support does not enable any live plan.

An older Quipu build may still reserve `urn:quipu:memory:*` subjects for its
private primitive. ST retains these existing revision/snapshot identifiers for
outbox continuity and does not route around that refusal by renaming them.
Ordinary-route qualification and activation therefore require the reviewed
primitive removal to arrive through the normal Quipu release/install path.
A source implementation or passing RDF-engine fixture does not discharge that
installed dependency or the separate private-upload hold.
