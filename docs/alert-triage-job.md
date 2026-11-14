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
