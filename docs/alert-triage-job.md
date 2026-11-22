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
