# Shantytown

**A crew of AI agents for shipping software and running everyday operations:
part of the Quipu stack.** Shantytown turns work items into coordinated agent
work, with ownership, capacity limits and a record of what happened.

![How a work item moves through a crew: ask, dispatch, work, stop and deliver. The administrator dispatches, a worker works in its own pane and takes its next item at each stop, and a reviewer agent can review the change. Under each stage is the part of the Quipu stack that serves it: Chaski and Shuttle trigger an item, Seeds and Quipu say who owns what, Bobbin and Yupana inform and constrain the work, Camayoc and Desire Path account for it, and Quipu remembers the outcome. Every stack tool is optional.](diagrams/work-item-lifecycle.svg)

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

Dispatch directly with `st go`, start a short-lived agent for one job with
`st agent spawn --ephemeral` ([ephemeral agents](ephemeral-agents.md)), or
declare a [scheduled or event job](jobs.md).

Shantytown does not run cron jobs. A scheduled job is a declaration in Quipu,
written with `st work jobs new`, for Chaski to fire. Job files with an event
trigger still load during a migration window; job files with a `cron` or
`every` trigger are refused. [Jobs](jobs.md) states what fires today and what
is still being moved.

A host timer calls `st fleet tend` every few minutes. Each pass supervises the
crew: it restarts an agent that died, enforces deadlines and limits, and can
feed an idle agent its next item. Nothing of Shantytown's stays running
between passes.

[Workflows and events](workflows.md) describe the optional Quipu event path.
External Chaski reactions and signed Shuttle workflows can feed the same
crew. CDEvents provides a common format for deployment notifications; connect
the producers and reactions your installation needs.

## How it fits the Quipu stack

Shantytown works without Quipu, and can use it for shared work, policies and
memory. The Quipu stack is built around a governed, bitemporal knowledge store:
Quipu records provenance and can check writes against configured rules.
Valid time is supplied per fact and write enforcement is opt-in; see the
[Quipu book](https://intigraph.github.io/quipu/).

| tool | role in a configured crew |
|---|---|
| Quipu | Optional shared knowledge and registry data. Local pane and process state still belong to the runtime. |
| Seeds | A Quipu-backed work tracker, selected through the tracker backend. |
| Bobbin | Code search and context for a work item. |
| Yupana | Code structure and impact checks through registered hooks. |
| Camayoc | Prepare and publish knowledge for the shared store. |
| Desire Path | Capture repeated agent mistakes as improvement requests. |
| Tambo | Review and install tool versions, including its crew profile. Its reviewed pins can trail newer releases. |
| Chaski and Shuttle | Optional external reactions and workflows that can hand work to the crew. |

Most of these reach an agent through hooks. A tool registers its hooks once
with `st ops hooks register`. Shantytown writes them into the settings of each
agent program beside its own, and they run at fixed points of a session:

![What reaches an agent during a session. A stack tool registers a hook bundle, Shantytown writes one settings file per role and the agent program runs the hooks at four points. At session start, st anchor gives identity, plate and lead, and Yupana briefs the agent on its work item. At each prompt, Shantytown recalls earlier incidents and Bobbin adds matching code. At each tool call, Shantytown captures tools, files and tokens, Yupana checks an edit against policies and reports its impact, and Desire Path records a failed call. At stop, Shantytown decides between the next item, a report to the lead and rest, and Quipu asks the agent to record what it learned.](diagrams/session-hooks.svg)

## Capability status

Release 0.22 supports:

- work ownership, capped plates and dispatch that respects a busy session;
- roles with a reporting chain, across more than one host
  ([a crew across hosts](multi-host.md));
- four agent programs: Claude Code, Codex, OpenCode and, experimentally,
  Antigravity ([harnesses](harnesses.md));
- five trackers: files, beads, `br`, Seeds and Forgejo issues
  ([adapters](adapters.md));
- short-lived supervised agents for one review, merge, triage or task
  ([ephemeral agents](ephemeral-agents.md));
- a governor over provider usage windows, session ceilings and quiet-time holds;
- due dates on work items, coming-due briefs and
  [overdue reminders](overdue-reminders.md);
- [scope changes](rescope.md) that the item's owner acknowledges, with Seeds.

Most controls are off until a deployment enables them.
[Features](features.md) describes each one, [Configuration](configuration.md)
lists the settings and [The CLI](cli.md) lists the commands. A feature that
exists in a release still needs your configuration and a check on your own
host before a running crew relies on it.

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
