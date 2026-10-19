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

The versioned transport candidate adds a bounded remote client. It reuses the
administrator-owned named CLI credential selection; card aliases resolve only
through that explicit mapping. It does not derive an owner IRI from a card name.
The server must verify the selected named principal for own writes/projection;
a shared-token fallback cannot establish that identity. Ordinary cross-crew
reads stay available.

Remote own staging validates the authenticated owner, complete owner manifest,
identified revisions, exact UTF-8 bytes, hashes and lengths. Network timeout or
conflict retains an unknown/conflict result without retrying or changing local
files. This client is not yet a lifecycle hook or an accepted native harness
adapter. Existing startup bridge behavior remains in place.

The outbox library keeps immutable intents and verified receipts in an existing
private, user-owned directory. Each delivery reads the exact intent's receipt
before attempting at most one commit. Unknown outcomes preserve the intent;
there is no retry loop. A lost response can be reconciled on a later ordinary
trigger without another commit. A locally accepted delivery makes no network
request and does not rewrite the receipt or advance source-change freshness.
Corrupt, partial, linked or mismatched records refuse. These libraries still
require lifecycle and native adapter integration before they can replace the
startup bridge.

The explicit memory CLI can inspect source metadata, read manifests, query
attributed historical text or export a selected owner's bounded records.
Query scope is one explicitly selected owner/repository, not a global search
index. Own staging and writes retain their separate named-identity requirement.
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
the authenticated own remote head to equal the previously accepted head. Its
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
uninterruptible OS operation, or a fixed orphan-reaping latency. They do not yet
install a startup/stop hook or select a native directory. Lifecycle wiring and
supported native handoff remain required before activation.

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
account = "legacy" # or the exact selected named Claude account
source = "/private/alpha/original-memory"
outbox = "/private/alpha/outbox"
staging = "/private/alpha/generations"
```

The administrator must select the crew member's actual existing native memory
root, not a directory inferred from a similarly named account. The source,
outbox and staging directories must already exist, be distinct and nonoverlapping;
outbox and staging must be private and user-owned. A named crew CLI credential
selection is mandatory. Its selected token is resolved through the existing
credential provider, independently of the administrator's ambient token, and
the server must confirm the exact principal on own projection/write. An existing
credential refusal latch is never refreshed or bypassed by this path.

For an enabled Claude plan, normal managed launch preparation reconciles at
most one pending intent under the two-second worker budget. Pending batches,
conflicts, unknown identity, unavailable transport or unsafe settings refuse
that launch promptly; they do not silently select an older remote head. A
bounded refusal is not permission to retry, cycle a crew member or enable a
canary. The input settings must be regular, single-link, user-owned and not
group/world writable. Existing settings, hooks, permissions and environment are
copied into a new private artifact; the role's original artifact is untouched.

Only after own-authenticated projection agrees with the accepted head **and**
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
The same configured source/account/owner identity must match the journal. An
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
