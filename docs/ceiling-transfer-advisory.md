# Ceiling-transfer observations

The existing fleet ceiling-transfer sweep writes local observations to
`<root>/ceiling-transfer-advisory.jsonl`. It uses the same budget, owner-count,
roster findings and planner inputs used by the ordinary dispatcher. It adds no
tracker reads, eligibility rule, dispatcher, hold, timer or forced tend pass.
Normal `tend --dry-run` still skips the fleet sweep; it is not evidence of
natural fleet exposure.

Each invocation has a random `sweep` identifier. Every row names the policy,
reviewed claim promotion digest (`policy_version`), SHA256 of the three producer
modules, timestamp, phase, dry-run flag, effect `record` and adjudication
`ungraded`. A code digest identifies the files read during capture, not proof
that another process loaded the same bytes. Installation acceptance must verify
the actual invoking process and source revision separately.

Phases:

- `start`: the invocation was reached, before its reads. A start without a later
  phase has UNKNOWN input coverage, never an empty or successful population.
- `held`: the existing gaming gate returned before reading inputs.
- `no_holders`: the original budget/source scan found no held open plate item;
  receiver eligibility was not evaluated. The captured findings distinguish an
  unresolved limit from an acted fallback. This is not a receiver-headroom proof.
- `plan`: contemporaneous cached budget tuples, source evidence, candidates,
  actually observed counts (including null for UNKNOWN), proposed moves and
  stays. Missing count keys mean not read. A candidate's placeholder `assigned`
  value does not turn an absent/null count into a complete zero.
- `outcomes`: results from the SAME ordinary dispatcher. `confirmed`, `refused`,
  `delivered_untracked`, `unproven` and `not_attempted` remain distinct. A plan
  without outcomes does not prove delivery, refusal or permission to retry.
  Comment confirmation is recorded separately from delivered work.

The observer writes private append-only rows. A capture error reports UNKNOWN
and does not change dispatcher behavior or retry a handoff. A partial final JSON
line or missing phase is UNKNOWN coverage. Record the error population when
assessing exposure; do not silently discard malformed or incomplete rows.
The ledger is local evidence, not a public artifact; review and redact it before
sharing. Existing source notes/checkpoints still accompany the handoff.

## Independent adjudication

Use naturally produced rows after normal installation. Preserve raw bytes and
code/policy identities, group phases by sweep, and have a non-author judge each
finding against its contemporaneous source and receiver evidence. Include
refusals, stays, UNKNOWN inputs and incomplete observations, not only successful
moves. Known inactive budget policy permits headroom; signal loss or missing
attribution for an active policy does not. Receivers must be distinct live Claude
workers with complete under-cap counts and the existing dispatch gates.

Report independently judged incorrect findings / all independently judged
findings, with explicit unknown and ungraded populations and observation window.
Zero judged findings means rate UNKNOWN, not zero. Offline tests are controls,
not operational exposure or adjudication. No effect increase is automatic; the
policy owner must accept the measured evidence separately. Revert the source
change through the normal reviewed path to stop capture; do not delete retained
observations or undo already delivered work.
