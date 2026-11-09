# Stop spec-notice evidence

Spec notification has separate facts: generation output (`EMITTED`), an accepted
harness input containing that output (`HARNESS_OBSERVED`), and owner ACK. None
implies comprehension. Inbox delivery and the existing pre-emission deduplication
fence cannot establish harness observation. Missing evidence is `UNKNOWN`, never
proof of nondelivery. Historical notices without this evidence stay UNKNOWN.

The existing Stop `haul` generator optionally reads the currently available hook
stdin, bounded to 16 KiB. Only an actual Stop payload supplying `session_id` and
`hook_run_id`, plus the existing recipient/card harness identity, enables evidence.
Missing fields leave the original pointer and its deduplication unchanged. No IDs
are synthesized from time or the active work item.

Each generated notice's canonical body SHA-256 is bound to agent, harness, session,
hook run, item and exact generation. An appended opaque `spec-observation` digest
binds the complete batch of identities into the actual output. The original body
still has its 400-byte cap; instrumented output is capped at 512 bytes. Different
hook runs or generations have different tokens even if their readable text is
identical. Stored evidence contains identities and digests, never notice bodies.

The existing stats Stop capture is the optional receiver observer. Its conservative
Codex archive adapter accepts only a session-bound, complete JSONL capture containing
a native `turn_context.payload.turn_id` followed by a `response_item` of type
`message`, role `user`, with a native message `id`, matching native message turn
metadata, and exactly one `input_text` block equal to the emitted wire text. This
adapter follows the accepted Stop-input structure observed in preserved archives;
matching the exact new notice envelope remains a separately qualified live gate.
Tool output, developer/assistant messages, diagnostic events, wrapping or
ambiguous text, missing turn identity, unsupported schemas and partial captures do
not qualify. The source's accepted input record proves observation; generator stdout
and successful subprocess exit do not. The receiver identity explicitly names the
native message ID and native turn, supplemented by archive ordinal and record digest.
Missing or disagreeing native message/turn identity stays UNKNOWN. Other harness
schemas remain UNKNOWN.

Evidence is private (0600 files, newly created directories 0700), immutable, and
published atomically without replacement under `notify/spec-observation`. Directory
descriptors pin evidence paths against ancestor symlink retargeting. Same-event
replay preserves receipt bytes and mtime. Reads/writes cap the ledger at 256 entries,
individual entries at 4 KiB and a source archive at 8 MiB. Exhaustion disables new
evidence; it never resends notices or ACKs. Preserve the original ledger when doing
any separately authorized archival maintenance.

The exact reader is the library `spec_observation.show(root, identity)` or:

```sh
python -m shantytown.spec_observation /path/to/crew-root < identity.json
```

`identity.json` contains exactly `agent`, `harness`, `session`, `hook_run_id`, `item`,
`generation` (positive integer) and `body_sha256`. An identity mismatch cannot borrow
another generation's receipt. Results distinguish `emission` from `arrival` and
report the receiver identities supporting an observed arrival. Library callers may
also supply `receiver=` to require an exact source/turn/ordinal/record-digest match.
Corrupt or unreadable
evidence yields UNKNOWN. This reader does not read hook configuration or send/ACK.

Private fixture controls exercise the real generator and existing stats capture,
then the exact library/CLI reader: emission only, accepted native-shaped input,
drop, mismatches, unavailable observer, partial/capped input and duplicate replay.
These controls establish source behavior, not installed or live harness acceptance.
Native hook-field availability and the exact accepted Stop-input archive shape
still require separately scoped live qualification through normal deployment and
review. Unsupported deployed schemas must stay UNKNOWN; do not loosen matching to
make a receipt appear. No live controlled generation, runtime projection, automatic
resend or reconstruction of older arrival is authorized by this source change.
