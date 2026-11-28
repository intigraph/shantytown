# Summary

[shantytown](introduction.md)

- [Documentation map](map.md)

# The pitch

- [Why Shantytown?](why.md)
- [See it in action](tour.md)
- [Features](features.md)
- [Principles](principles.md)

# Running a town

- [Getting started](getting-started.md)
  - [Installation reference](installation-reference.md)
- [A crew across hosts](multi-host.md)
  - [New host setup](new-host.md)
  - [Second host setup](second-host.md)
- [Configuration](configuration.md)
  - [Configuration source](config-source.md)
- [The CLI](cli.md)
  - [Starting a session](cli-session.md)
  - [Dispatch and intake](cli-dispatch.md)
  - [Work items, gates and cost](cli-work-items.md)
  - [Creating and running a crew](cli-crew.md)
  - [Pane states and stops](cli-stops.md)
  - [Messages, memory and history](cli-messages.md)
  - [Supervision, holds and budgets](cli-supervision.md)
  - [Health and tooling](cli-ops.md)
  - [Pushes and pull requests](cli-repo.md)
  - [`st prime`](prime.md)
- [Routing](routing.md)
- [Workflows & events](workflows.md)
- [Roles](roles.md)
- [Harnesses](harnesses.md)
  - [Phone access to crew conversations](android-crew-sessions.md)
    - [Phone acceptance evidence](demos/android-crew-sessions/record.md)
  - [Local models and OpenCode](local-models.md)
  - [Design: the `agy` harness](design/agy-harness.md)
- [Incident recall](incident-recall.md)
- [Private stop samples](stop-samples.md)
- [Sleep / dream](dream.md)
- [Scheduled & event jobs](jobs.md)
- [Ephemeral agents](ephemeral-agents.md)
- [Everyday work with one agent](everyday-work.md)

# The shape

- [Vision](vision.md)
- [Design](design.md)
- [Agent card](agent-card.md)
- [Adapters](adapters.md)
- [Integrations](integrations.md)
- [The stop decision (spec)](stop-policy-spec.md)
- [Cross-harness handoff envelope](handoff-envelope.md)
- [Cycle advice: keep or cycle at a handoff](cycle-advice.md)
- [Durable browser handoffs](inbox-bridge.md)
- [Messages in their own graph (design)](message-graph.md)
- [MCP containment](mcp-containment.md)
- [Private-key checks](private-key-checks.md)

# Work and the board

- [Change a work specification](rescope.md)
  - [Spec-notice evidence](spec-observation.md)
- [Overdue and unlock reminders](overdue-reminders.md)
  - [Shared reminder transport](design/shared-reminder-ports.md)
  - [Targeted external-blocker reaction](design/targeted-unlock-reaction.md)
- [Automatic work refill](automatic-refill.md)
- [Governed rank proposals](board-rank.md)
- [Work classes and harness routing](work-class-routing.md)
- [Exact work-item context](work-context.md)
- [Work held by stopped owners](stopped-owner-work.md)
  - [Non-item duties](stranded-duties.md)
  - [Stopped-owner lifecycle observations](stopped-owner-graph.md)

# Agents and sessions

- [Context handoff](guides/context-cycle.md)
  - [Cycling with retained Git work](guides/cycle-bundle-custody.md)
- [Crew memory across harnesses](crew-memory.md)
- [Crew credentials at launch](crew-credentials.md)
- [Isolated, key-derived agent identity](agent-identity-migration.md)
  - [Optional signing observations](advise-signing.md)
- [Mounted storage for new worktrees](worktree-storage.md)
- [Runtime update replacement](runtime-updates.md)
- [Remote Control display hostnames](remote-control-host-identity.md)
- [Automatic notification risk](notification-risk.md)
- [Ceiling-transfer observations](ceiling-transfer-advisory.md)
- [Roster capacity observation](design/roster-capacity-demo.md)
- [Daily usage projections](daily-cost.md)
- [Native tool-call trace outcomes](native-trace-outcomes.md)
- [Codex release retention](codex-release-retention.md)
- [Inherited session-capture hooks](legacy-session-capture.md)

# Jobs and reviews

- [One declared occurrence](single-occurrence-jobs.md)
- [Read-only alert triage job](alert-triage-job.md)
- [Job slots](job-slots.md)
- [Fixed inbox child for scheduled delivery](scheduled-inbox.md)
- [Seed before scheduled assignment](scheduled-seeds.md)
- [Attended review reports and enqueue](attended-review-enqueue.md)
  - [Review enqueue acceptance](review-enqueue-acceptance.md)
- [PR queue policy prototype](pr-queue-policy.md)
- [Merge-time service admission](service-admission.md)
- [Verified-wake recruitment adapter](recruitment-adapter.md)
  - [Controller endpoint client](recruit-controller-endpoint.md)
  - [Inherited controller listener](recruit-controller-receiver.md)
- [Offline post-deploy watch template](examples/watch/README.md)

# Stores and vocabulary

- [Explicit private Seeds commands](seeds-credentials.md)
- [Shared Seeds projection reads](seeds-read-cache.md)
- [Read attribution at tracker boundaries](read-attribution.md)
- [Stable vocabulary readers](stable-vocabulary-readers.md)
- [Former-name contracts](compatibility/legacy-name-contracts.md)

# Releases and repository knowledge

- [Release checksums](releases.md)
- [PyPI publishing](pypi-publishing.md)
- [Repository share transport](repository-share.md)
- [Reviewed knowledge witnesses](knowledge/README.md)
