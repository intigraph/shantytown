# `st prime`

`st prime` follows `stack-prime/1`: a static tool primer, then a bounded,
read-only summary of the crew, your anchor and your lead. It shares anchor's
startup resolver, adapters, identity admission, plate ordering and lead-delivery
predicate. It does not run anchor's plate publication, role-rule/due views or
startup hooks, or create/assign/close anything. It opts out of the Seeds read
cache (including cache directories/locks/watermarks), and requires complete
assignment rows before reporting an empty plate.

Use `st prime [agent] --json` for structured output, `--brief` for 5–10 lines,
`--static` for offline orientation, or `--section <heading-prefix>` for one static
section. Global `--root`, `--registry`, `--backend` and `--repo` precede `prime`,
as they do for `anchor`. Explicit agent selection or `SHANTY_AGENT` selects the
card to read; identity admission remains the normal CLI boundary.

The live probe has a 650 ms deadline, including configuration and authentication.
A private child runs the shared read; timeout kills and reaps its local process
group, including reader children. Input is capped at 16 KiB, output at 64 KiB,
and the roster preview at 20 registered cards. The count is registered crew, not
an inferred running-process count. Only anchor's lead predicate reports delivery
reachability; null means unknown. Killing a client does not cancel server work,
so the probe uses anchor's existing scoped plate read, not a new board-wide scan.

`live.status` is `ok`, `partial`, `absent`, `unreachable`, `unreadable` or `skipped`.
Overall `status` is `ok` for `ok`/`skipped`, otherwise `degraded`; these states exit
0 and retain the primer. Unknown fields remain null. Usage errors exit 2. JSON
includes tool/version, `primer.sections`/`text`, `live.status`/`elapsed_ms`/`summary`
and overall `status`; `--brief --json` omits `primer.text`. Static and section
reads skip deployment configuration, actor admission and live adapters.

The packaged `shantytown/primer.md` is the source for runtime text and both copies
below and in the skill. Run `python3 scripts/sync-primer.py` to regenerate them;
normal pytest checks fail if they drift. `st anchor` keeps its existing startup
render and task-context schema.

<!-- BEGIN st prime -->
## Shantytown agent primer

### What Shantytown is
Shantytown (`st`) coordinates coding agents, their work and session lifecycle.
Crew cards define identity, role, lead and host; the selected tracker owns work.
Quipu supplies graph knowledge, Seeds tracks items, and Bobbin and Yupana supply code context.
Tambo installs the stack; `tambo prime` combines each tool's brief orientation.
`st anchor` is session startup context; `st prime` adds this tool primer around the same read.

### Agent workflow
1. Run `st anchor` to read your identity, current work and reporting route.
2. Query Quipu for existing facts and the deployment's process rules before acting.
3. Use Bobbin for semantic search and Yupana for structural impact before code changes.
4. Work your assigned plate; use `st work` for tracker changes and `st inbox -d` for durable reports.
5. Keep source, merged, installed and running evidence separate; inspect the result before closing work.

### Core commands

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

### MCP tools
None. Shantytown exposes the `st` CLI and Python library; connected Quipu, Bobbin
and Yupana tools belong to those services, not to a Shantytown MCP server.

### Next steps
- [CLI guide](https://github.com/intigraph/shantytown/blob/main/docs/cli.md) and [README](https://github.com/intigraph/shantytown#readme).
- [Shantytown skill](https://github.com/intigraph/shantytown/blob/main/skills/shantytown/SKILL.md) and [prime contract](https://github.com/intigraph/shantytown/blob/main/docs/prime.md).
- Run `st --help`, `st prime --help` and command-specific `--help`; this package does not currently ship a man page.
<!-- END st prime -->
