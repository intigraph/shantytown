# Read-only alert triage job definition

`shantytown.alert_triage_job.CATALOG_ENTRY` describes the first alert job.
It defaults OFF and grants no identities, credentials or launch capabilities.
This is separate from `job_catalog`'s identity-only `slots.json` inventory.

The offline compiler consumes three bounded, regular, SHA256-pinned JSON files:

- An existing identity-only slot, with its separately admitted exact allocation.
- Exactly the existing `job_manifest` launch fields. The request is triage on
  the original alert carrier item; repo/PR/checkout/head/request_id and review
  are null. The reviewed argv ends with `@READ_ONLY_ALERT_TRIAGE_PROMPT@` once.
- One input with exactly `version: 1`, `item`, `fingerprint_kind`, `fingerprint`
  and `onset_utc`. Use `escalation-bridge` for 12 lowercase hex digits or
  `alertmanager-native` for 16. UTC onset must come from the original episode.

Run `python -m shantytown.alert_triage_job --help` for the explicit file/hash
arguments. No environment substitution or runtime template expansion occurs.
The compiler emits private, new-only `bindings.json` and `compilation.json`.
The latter pins definition, canonical input, source file bytes, prompt and
bindings. Pass the bindings and their recorded digest to the existing
`python -m shantytown.job_manifest` renderer with the separately pinned
identity catalog. Neither existing manifest nor Request schema is extended;
unknown fields still refuse. The fingerprint is frozen into the argv prompt,
which is transitively covered by the rendered slot and catalog hashes.

The prompt allows only the job's separately admitted authenticated alert read,
scoped read-only poller evidence and original-item report route. It matches
the fingerprint namespace and original onset, names evidence/cause/keeper,
keeps ambiguous or unavailable evidence UNKNOWN, reports once through the
existing ephemeral reporter, and exits. It forbids ACK/silence/restart, pane
input changes, fixes, publication, credentials borrowed from crew/controller,
and manual ticks. A completed diagnosis is not a recovered alert.

Native reader permissions, immutable runtime closure, account allocation,
enrollment, controller delivery and actual launch acceptance are separate
admissions. Missing own readers/report authority blocks the job. The Gold
identity delivery lane still accepts only identity catalog files: do not put
these bindings or proof files in that input. Examples in tests use synthetic
UIDs and executable paths and must never be installed as host allocations.

Reproducible source demo and negative controls:
`python -m pytest -q tests/test_alert_triage_job.py` proves a frozen alert
becomes ordinary renderable bindings, while changed pins, duplicate keys,
extra fields, wrong item/kind/onset and prompt-marker ambiguity refuse.
This is offline source proof, not a live job or backend capability test.

## Signed report shadow contract (za4f.6)

`incident_report.validate(job, jobspec, report)` and `plan(validated, jobspec)`
are pure library functions. They have no launch or executor wiring. The current
read-only compiler and its `enabled=false` admission remain unchanged.
The controller must read the signed verdict from `st-gate-verdicts`, bind its
job/run/subject and incident to the frozen launch input, and verify evidence
provenance before any executor consumes an intent. Structural validation cannot
authenticate a report, establish that a reference is genuine, or prove an RCA.
A `Validated` instance alone is not authorization.

The future JobSpec prompt must request this exact JSON envelope:
`job`, `run_id`, `subject` (`kind`, `id`, optional full `head`), `verdict`,
`summary` (at most 400 UTF-8 bytes), `evidence` (up to 64 `{kind, ref}` pairs),
and `report`. This v0 validator admits only the `triage` job.
The report payload contains:

- `incident`: exact `source` (`alertmanager-native` or `escalation-bridge`),
  full `fingerprint` (16 or 12 lowercase hex characters respectively), UTC
  `onset`, `service`, `host`, and original `carrier_item`.
- `coverage`: `complete`, `partial`, or `unknown`.
- For `diagnosed`: nonempty `diagnosis`, `diagnosis_evidence` references all
  present in the envelope, and `proposed_fix` with `repo`, `scope`, and
  `verification`. Partial coverage cannot yield `diagnosed`.

All fields, including suggested repairs, remain untrusted data. No field is a
shell argument or grants repository/write authority. `needs-owner` and `unknown`
can preserve a partial result without inventing a fix. The configured verdict
and route lists are authoritative; missing routes produce no intents.

The resolved spec envelope is exactly `{resolved, sha256}`, hashing UTF-8 JSON
with sorted keys, compact separators, literal Unicode and no nonfinite numbers.
The snapshot stores JSON rather than mutable caller dictionaries. Planning
revalidates the report and spec hash. Its initial action vocabulary is
`comment-item`, `file-followup`, and `notify-owner`; unknown or duplicate names
refuse the entire plan. This vocabulary must be reconciled with the shared
registry owned by za4f.2 before integration; it is not a second executor.
Each intent carries copied JSON arguments and SHA256 of canonical
`[run_id, action, args]`. A changed payload changes the key. Registry idempotency,
write reconciliation, admission and execution remain controller responsibilities.

## Shadow consumer (za4f.6.1, step H1)

`incident_consumer.consume(record, frozen=..., jobspec=..., journal=..., verified=True)`
takes ONE report record that the signed reader has already verified and returns
the shadow intents, journaled once.
`consume_event(raw, frozen=..., jobspec=..., journal=..., verified=True)` takes the
serialized event form, a JSON object of exactly `kind: "incident_report"`, `record`,
`frozen` and `jobspec` (at most 1 MiB), so a recorded event can be replayed;
`tests/fixtures/incident_consumer/triage-event.json` is one. `verified` must be
exactly `True`; the caller that read `st-gate-verdicts` and checked the signature
sets it, this module does not authenticate.

`verified` covers the **record only**. `frozen` and `jobspec` are trusted launch
state and always come from the caller (the launcher's own copy). The event's
embedded copies are provenance, not input: if either differs from the trusted
one, the event is refused as `launch-mismatch` and recorded with the digests of
both copies. Otherwise a forged or replayed event could carry a frozen input that
matches its own report and a jobspec whose `sha256` is computed over its own
routes, so it would vouch for its own incident binding and actions. Then:

1. requires a journal directory that is a real directory owned by the caller and
   not writable by group or others, otherwise `journal-dir` (the only refusal
   that is not recorded: there is nowhere safe to write it);
2. requires the frozen launch input to have exactly `version: 1`, `item`,
   `fingerprint_kind`, `fingerprint` and `onset_utc`;
3. runs `incident_report.validate` and `plan` unchanged;
4. binds the report to THIS incident: `incident.source`, `fingerprint`, `onset`
   and `carrier_item` must equal the frozen `fingerprint_kind`, `fingerprint`,
   `onset_utc` and `item`, otherwise `incident-binding`. Onsets compare as the
   same instant: `04:00:00Z` equals `04:00:00.000Z`, trailing fraction zeros aside;
5. writes `<sha256(run_id)>.json` (mode 0600, fsynced, created exclusively by a
   hard link, at most 1 MiB or `record-too-large`). The same run twice returns the
   same intents with `replay=True` and one file; the same run with different
   content refuses `run-rebound` and leaves the first record unchanged; a record
   that cannot be parsed refuses `journal-unreadable` and is left for an operator.

Refusals and UNKNOWN are recorded, not dropped. An `unknown` verdict journals an
intent record with no intents. Every refusal after step 1 writes
`refusal-<sha256>.json` once, keyed by reason plus the digests of the record, the
frozen input and the jobspec, holding `reason`, `record_sha256`, `frozen_sha256`,
`jobspec_sha256` (plus `event_frozen_sha256`/`event_jobspec_sha256` for
`launch-mismatch`) and the `run_id` when one is readable, never the untrusted
record itself. The same refusal twice is one record; the same record refused under
two different specs is two.

A journal write that fails (`ENOSPC`, `EIO`, `EXDEV` from the link or an fsync)
is **fatal**: the `OSError` propagates and no `.pending-` file is left. The event
source must treat the exception as not consumed and redeliver. A fault before the
link journals nothing (not even a refusal, since the journal itself failed), and the
redelivery is consumed normally, once. A fault in the directory fsync *after* the
link succeeded leaves the record in place and still raises; the redelivery then
returns `replay=True` with the same intents. A malformed event includes one nested
too deeply to parse (`json.loads` raises `RecursionError`, not `ValueError`): it is
refused as `event-shape` and recorded like any other. Each distinct refused record
or garbage event writes its own refusal file, so the journal is unbounded under
hostile input; accepted for the H1 shadow, and H2 must bound it. Files starting `.pending-` are crash leftovers of an
interrupted write; readers ignore dot-files.

It imports no launcher, signer, executor, queue or network code, and creates no
seed, comment or job. The journal is H2's input (signed verdict -> fix-seed
executor), not an action. Source proof: `python -m pytest -q tests/test_incident_consumer.py`
(breaking the binding, the `verified` check, the rebound check, the symlink check,
refusal recording, onset normalisation or the size cap each turns tests red; the
fsyncs are durability only and no test detects their removal). No runtime
activation, no chaski route yet.
