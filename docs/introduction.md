# Shantytown

**A crew of AI agents for shipping software and running everyday operations:
part of the Quipu stack.** Shantytown turns work items into coordinated agent
work, with ownership, capacity limits and a record of what happened.

## A software factory

Give a crew a concrete outcome and divide it into work with named owners.
Agents can investigate, implement, test, review and deliver changes through
your repository's normal checks and permissions. Dispatch checks whether a
session is ready; it does not type over a busy agent. The governor evaluates
capacity, account observations and holds before admitting more work.

Your repository and deployment configuration supply the review, merge and
publication permissions the crew follows.

## Everyday operations

The same crew and work items can organize research, follow-up work and other
everyday responsibilities. You provide the workflows, context and access.
Configure the workflows your crew needs, and keep private context in your own
store. You choose which information can be shared with its tools.

## Work by hand, on a schedule or after an event

Dispatch directly with `st go`, or declare a [scheduled or event job](jobs.md).
Jobs can use cron expressions, intervals or event sources. A host scheduler
must call `st fleet tend` regularly: Shantytown evaluates due work during each
pass and records its result. The scheduler cadence bounds when a job fires;
it is not a real-time clock.

[Workflows and events](workflows.md) describe the optional Quipu event path.
External Chaski reactions and signed Shuttle workflows can feed the same
crew. CDEvents provides a common format for deployment notifications; connect
the producers and reactions your installation needs.

## How it fits the Quipu stack

Shantytown works without Quipu, and can use it for shared work, policies and
memory. The Quipu stack is built around a governed, bitemporal knowledge store:
Quipu records provenance and can check writes against configured rules.
Valid time is supplied per fact and write enforcement is opt-in; see the
[Quipu book](https://scbrown.github.io/quipu/).

| tool | role in a configured crew |
|---|---|
| Quipu | Optional shared knowledge and registry data. Local pane and process state still belong to the runtime. |
| Seeds | A Quipu-backed work tracker, selected through the tracker backend. |
| Bobbin | Code search and context for a work item. |
| Yupana | Code structure and impact checks through registered hooks. |
| Camayoc | Prepare and publish knowledge for the shared store. |
| Desire Path | Capture repeated agent mistakes as improvement requests. |
| Caboodle | Review and install tool versions, including its crew profile. Its reviewed pins can trail newer releases. |
| Chaski and Shuttle | Optional external reactions and workflows that can hand work to the crew. |

## Capability status

The release supports work ownership, capacity-aware dispatch, per-role and
per-agent configuration, session ceilings, account observations, pauses while you are gaming,
and declared scheduled/event jobs. See [Features](features.md),
[Configuration](configuration.md) and [The CLI](cli.md).

The new due-date defaults, coming-due briefings, overdue notifier and
owner-confirmed scope changes are still source work in review. They require
normal source CI, review, installation and configured delivery before running
crews can rely on them. An available SDK primitive alone does not prove that
the crew UI or its notifications have adopted it.

### Capacity report example

A live report sampled on **2026-10-15 at 04:17 UTC**, from `st crew --governor`
on the **development build 0.7.1 (31e6773-dirty)**, produced these anonymized observations:

| account | five-hour window used | weekly window used | live agents / admitted cap |
|---|---|---|---|
| 1 | 31% | 33% | 9 / 9 |
| 2 | UNKNOWN | 63% | 6 / 12 |

These are quota observations and evaluated caps at one time, not absolute
available tokens, spending reductions or a throughput benchmark. Session
ceilings separately limit hours, work items and production actions. Unknown
windows remain unknown; eligibility and operator holds still govern any
handoff or account/harness change. No measured saving from rerouting or gaming
holds is claimed by this sample.

## Start here

[Getting started](getting-started.md) walks through the first crew.
[Scheduled and event jobs](jobs.md) explains triggers and host scheduling.
[The CLI](cli.md) provides every command and exit code.
