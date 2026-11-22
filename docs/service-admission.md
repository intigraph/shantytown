# Merge-time service admission

The `Service admission / service-admission` merge-group job runs the shared
controller gate from trusted installed source, without checking out candidate
code. It uses isolated Python and a read-only GitHub token. Event values are
quoted arguments; native queue observations and protected controller custody
establish identity and permission.

Rollout is disabled until `SERVICE_ADMISSION_REQUIRED=true`. Before enabling it,
install the qualified controller source on a dedicated `service-admission`
runner and set `AEGIS_SERVICE_ADMISSION_GATE` to its absolute entrypoint path.
Use the normal ownership-neutral execution-source deployment and verify its
exact revision. The configured controller host and UID must agree; absent,
invalid or unreadable custody refuses. Make the job required for the queue
before declaring enforcement. A missing executable fails the enabled job.

The gate refuses held, withdrawn, missing or mismatched admission receipts,
changed heads/queue entries, missing predecessor proofs, incomplete native
snapshots and unbound merge trees. It checks the immutable group tree against
GitHub's test merge with exact base/head parents. Initially only one-entry
groups qualify; other groups wait for regeneration or future combined-tree
qualification. This is a conservative support limit, not a bypass.

After source lands, controls pass and a refusal replay succeeds, activation
follows the operator's accepted rollout contract. Verify the installed runner
with a separately admitted real queue run. Existing producer enrollment,
protected custody and signed-review requirements still apply.

A remote merge may race the last check. The accepted incident procedure is an
exact-main watch, same-hour revert and an item record; more than two incidents
in fourteen days reopen the work. Disable new handoffs first during rollback,
preserve withdrawal intents/fences and reconcile remote outcomes before
removing enforcement. Never turn uncertain remote work into a fresh attempt.
