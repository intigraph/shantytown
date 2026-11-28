# Documentation map

Start with [Getting started](getting-started.md) for a first crew, or
[Features](features.md) for what Shantytown does today. The sidebar lists
every chapter; this page routes by task.

## Learn what it is

| need | read |
|---|---|
| The two uses and how it fits the Quipu stack | [Introduction](introduction.md) |
| The case for it and the alternatives | [Why Shantytown?](why.md), [principles](principles.md) |
| Sample sessions | [See it in action](tour.md) |
| The current capabilities | [Features](features.md) |

## Set up and run a crew

| need | read |
|---|---|
| Install, pin a release or remove it | [Installation reference](installation-reference.md) |
| Create and launch a first crew | [Getting started](getting-started.md) |
| Add a host | [New host](new-host.md), [second host](second-host.md) |
| Configure accounts, backends and controls | [Configuration](configuration.md), [configuration source](config-source.md) |
| Every command and exit code | [The CLI](cli.md), [`st prime`](prime.md) |
| One group of commands in depth | The pages under [The CLI](cli.md#where-each-command-is-described): sessions, dispatch, work items, crews, stops, messages, supervision, tooling and pushes |
| Choose agent programs and models | [Harnesses](harnesses.md), [local models](local-models.md), [work classes](work-class-routing.md) |
| Choose roles and reporting lines | [Roles](roles.md), [agent card](agent-card.md) |
| Reach a crew from a phone | [Phone access](android-crew-sessions.md) |

## Give the crew work

| need | read |
|---|---|
| Send messages and dispatch items | [Routing](routing.md), [tour](tour.md) |
| Run a short-lived agent for one job | [Ephemeral agents](ephemeral-agents.md) |
| Declare a routine or react to an event | [Jobs](jobs.md), [workflows](workflows.md), [one occurrence](single-occurrence-jobs.md) |
| Use one agent for everyday tasks | [Everyday work](everyday-work.md) |
| Change an item's scope with its owner in view | [Rescope](rescope.md) |
| Remind owners of overdue and unblocked work | [Overdue reminders](overdue-reminders.md) |
| Keep idle agents fed from a ranked backlog | [Automatic refill](automatic-refill.md), [rank proposals](board-rank.md) |
| Recover work held by a stopped agent | [Stopped owners](stopped-owner-work.md), [duties](stranded-duties.md) |

## Keep sessions healthy

| need | read |
|---|---|
| Hand off before a context window fills | [Context handoff](guides/context-cycle.md), [cycle advice](cycle-advice.md) |
| Carry memory and credentials between sessions | [Crew memory](crew-memory.md), [crew credentials](crew-credentials.md) |
| Replace a running agent program after an update | [Runtime updates](runtime-updates.md) |
| Decide what interrupts the administrator | [Notification risk](notification-risk.md), [stop policy](stop-policy-spec.md) |
| Recall earlier incidents | [Incident recall](incident-recall.md) |

## Connect other tools

| need | read |
|---|---|
| Trackers, registries and pane adapters | [Adapters](adapters.md) |
| Quipu, Seeds, Bobbin and Yupana | [Integrations](integrations.md) |
| Seeds reads, credentials and attribution | [Seeds commands](seeds-credentials.md), [read cache](seeds-read-cache.md), [read attribution](read-attribution.md) |
| Review and merge automation | [Attended review enqueue](attended-review-enqueue.md), [PR queue policy](pr-queue-policy.md), [service admission](service-admission.md) |

## Understand the design

| need | read |
|---|---|
| Why it is built this way | [Vision](vision.md), [design](design.md) |
| Delivery and safety choices | [Stop policy](stop-policy-spec.md), [MCP containment](mcp-containment.md), [private-key checks](private-key-checks.md) |
| Messages and handoffs | [Message graph](message-graph.md), [handoff envelope](handoff-envelope.md), [browser handoffs](inbox-bridge.md) |

## Releases

[Release checksums](releases.md), [PyPI publishing](pypi-publishing.md) and
the [repository share](repository-share.md) describe what a release publishes.

## Evidence records

The directories `docs/demos/`, `docs/probes/` and `docs/pr-demos/` in the
[repository](https://github.com/intigraph/shantytown/tree/main/docs) hold
recorded runs that accompanied individual changes: a script, its output and
its timing. They are evidence for the change they shipped with, not current
reference, and are not part of this book. The
[terminal preview recipe](https://github.com/intigraph/shantytown/blob/main/docs/demos/terminal.md)
is the one the README embeds.
