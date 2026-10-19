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
