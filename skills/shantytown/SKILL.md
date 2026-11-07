---
name: shantytown
description: Orient a coding agent to Shantytown, its own anchor, crew and reporting route.
---

Run `st prime` for tool orientation, then `st anchor` for normal session startup.
Use the deployment's existing tracker and identity selection. A degraded live
summary means unknown state; it does not authorize initialization, reassignment
or credential changes.

<!-- BEGIN st prime -->
### Shantytown agent primer

#### What Shantytown is
Shantytown (`st`) coordinates coding agents, their work and session lifecycle.
Crew cards define identity, role, lead and host; the selected tracker owns work.
Quipu supplies graph knowledge, Seeds tracks items, and Bobbin and Yupana supply code context.
Tambo installs the stack; `tambo prime` combines each tool's brief orientation.
`st anchor` is session startup context; `st prime` adds this tool primer around the same read.

#### Stack orientation
Quipu stores governed knowledge; Seeds (`sd`) tracks work items. Camayoc (`cy`)
provides typed agent memory: recall decisions and directives before acting, and
record authorized rulings and handoffs through the deployment's governed path.
Read the provisioned Camayoc skill, `cy prime --static` and
`cy record <entity> --help` where installed. Its selected Jev MCP tools are
`jev_noul`, `jev_choice`, `jev_score`, `map_question` and `jev_dry_run`.
MCP configuration and permissions come from the deployment's tooling manifest.
An absent command or unavailable schema is UNKNOWN; refused writes retain their
gate. Orientation grants no write permission and does not provision `cy mcp`.

Bobbin searches code by meaning; Yupana traces structural impact. Tambo installs
the stack; `tambo prime` combines its tool primers (`stack-prime/1`). Chaski handles
reactions, Shuttle runs signed workflows, Rikuy presents the live brief, and
Desire Path records failed tool calls. Run `st prime` for the full primer and a
bounded crew/anchor summary. Startup uses this packaged section without invoking
other tools or contacting services.

#### Agent workflow
1. Run `st anchor` to read your identity, current work and reporting route.
2. Query Quipu for existing facts and the deployment's process rules before acting.
3. Use Bobbin for semantic search and Yupana for structural impact before code changes.
4. Work your assigned plate; use `st work` for tracker changes and `st inbox -d` for durable reports.
5. Keep source, merged, installed and running evidence separate; inspect the result before closing work.

#### Core commands

| Command | Use |
| --- | --- |
| `st prime --brief` | Read a compact stack primer and bounded crew/anchor summary. |
| `st anchor [agent]` | Read session identity, one current item and the lead's delivery status. |
| `st crew` | Inspect the crew; optional modes inspect capacity and worktrees. |
| `st task <title>` | Capture a work item on the configured tracker. |
| `st work item show <id>` | Inspect an exact work item before acting. |
| `st work item update/comment/close` | Record authorized tracker changes and evidence. |
| `st work defer <id> <kind>` | Record an external gate and a concrete resume condition. |
| `st inbox [-d] <agent>` | Read messages or send an authorized durable handoff. |
| `st go <item> <agent>` | Dispatch ready work through normal admission checks. |
| `st agent spawn --ephemeral` | Administrators launch one supervised, bounded job. |
| `st repo worktree <repo>` | Obtain an isolated checkout before editing. |
| `st ops doctor` | Diagnose the installation before changing it. |

#### MCP tools
None. Shantytown exposes the `st` CLI and Python library; connected Quipu, Bobbin
and Yupana tools belong to those services, not to a Shantytown MCP server.

#### Next steps
- [CLI guide](https://github.com/intigraph/shantytown/blob/main/docs/cli.md) and [README](https://github.com/intigraph/shantytown#readme).
- [Shantytown skill](https://github.com/intigraph/shantytown/blob/main/skills/shantytown/SKILL.md) and [prime contract](https://github.com/intigraph/shantytown/blob/main/docs/prime.md).
- Run `st --help`, `st prime --help` and command-specific `--help`; this package does not currently ship a man page.
<!-- END st prime -->
