<p align="center"><img src="assets/logo.svg" alt="shantytown" width="200"/></p>
<h1 align="center">shantytown</h1>
<p align="center"><em>🏭 Ship software and organize everyday work with a crew of AI agents.</em></p>
<p align="center">
<a href="LICENSE"><img alt="Apache-2.0 license" src="https://img.shields.io/badge/license-Apache_2.0-blue"/></a>
<a href="https://github.com/scbrown/shantytown/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/scbrown/shantytown/actions/workflows/ci.yml/badge.svg"/></a>
<a href="https://github.com/scbrown/caboodle"><img alt="Quipu stack" src="https://img.shields.io/badge/stack-quipu-8B5E3C.svg"/></a>
</p>

**A crew of AI agents for shipping software and running everyday operations:
part of the Quipu stack.** Use it to coordinate a software factory where agents and CI plan, build,
check and deliver changes, or for personal operations such as research and
follow-up work. You supply the goals, tools and access; the same work items,
ownership and controls organize both. Quipu integration is optional.

## Why you would want it

- Keep a software delivery crew on track: give work an owner, respect busy
  sessions, and connect the crew to your repository's checks and review policy.
- Organize everyday responsibilities with the same tasks and shared context;
  configure the workflows and information your crew needs.
- Run work by hand, on a schedule or after an event, with explicit capacity
  limits and a recorded outcome. See the [book](https://scbrown.github.io/shantytown/).

## Install

Python 3.11+, [pipx](https://pipx.pypa.io/) and `tmux` are prerequisites.
Install the verified wheel from the [latest release](https://github.com/scbrown/shantytown/releases/latest):

```sh
curl -fLO https://github.com/scbrown/shantytown/releases/download/v0.7.1/shantytown-0.7.1-py3-none-any.whl
curl -fLO https://github.com/scbrown/shantytown/releases/download/v0.7.1/SHA256SUMS
grep 'shantytown-0.7.1-py3-none-any.whl$' SHA256SUMS | shasum -a 256 -c
pipx install ./shantytown-0.7.1-py3-none-any.whl
export PATH="${PIPX_BIN_DIR:-$HOME/.local/bin}:$PATH"
st --version
```

The release reports `st 0.7.1`. The PATH line makes the new command available
in this shell. For future shells, run `pipx ensurepath` and open a new terminal.
To install from source instead:

```sh
git clone https://github.com/scbrown/shantytown
pipx install ./shantytown
```

Choose an installed [agent harness](https://scbrown.github.io/shantytown/harnesses.html)
and configure a tracker in [Getting started](https://scbrown.github.io/shantytown/getting-started.html).

## First success in three commands

Preview a two-agent crew in an empty directory. This writes nothing and launches no session:

```sh
mkdir shantytown-demo && cd shantytown-demo
st --root .shanty --backend files fleet init -y --admin coordinator --crew builder --dry-run
```

Expected preview:

```text
  store    .shanty
  dir      crew/
  dir      settings/
  dir      events/
  dir      launched/
  card     coordinator  administrator  pane st-coordinator
  card     builder      worker         pane st-builder
  hooks    settings/administrator.settings.json
  hooks    settings/worker.settings.json
  permissions for NEW cards: MANUAL (approval prompts enabled)
  config   .shanty/shantytown.toml

  2 agent(s) · startup mode 'lite' · hibernate off

  --dry-run: nothing written.
```

To preview just one administrator, use an empty worker list:

```sh
st --root .shanty --backend files fleet init -y --admin coordinator --crew "" --dry-run
```

The preview shows the crew, hooks and approval mode before you commit to running it.
Follow [Getting started](https://scbrown.github.io/shantytown/getting-started.html) to create and launch the crew.

## On your own code

With a configured project and crew, use the ID returned by your tracker in place of `st-1`:

| question | command |
|---|---|
| What does this item need? | `st work item show st-1` |
| Create a task | `st task "check the next release"` |
| Give it to an agent | `st go st-1 builder` |
| Who is working on what? | `st crew` |
| What can this agent do next? | `st anchor builder` |
| What recurring jobs are declared? | `st work jobs list` |

The [full CLI reference](https://scbrown.github.io/shantytown/cli.html)
lists every command and its exit codes.

### High-level capabilities

- **Work ownership and plate caps:** admit work within configured limits and
  respect busy sessions.
- **Software delivery:** connect planning, implementation and review to your
  repository's CI and delivery rules.
- **Scheduled and event work:** declare cron, interval or event jobs and
  arrange regular `st fleet tend` passes with your host scheduler.
- **Governor:** inspect account/window quota observations, live caps and
  session ceilings. Eligible handoffs retain their guards, and a gaming-session pause prevents
  new local work from starting.

**In review:** due-date defaults and coming-due briefs, overdue reminders,
and scope changes confirmed by the responsible owner. These need release, configuration and verified
delivery before running crews can rely on them.

The [capability status and measured governor example](https://scbrown.github.io/shantytown/introduction.html#capacity-report-example)
retain their date, units and UNKNOWNs. Quota percentages and counters do not measure tokens saved.

## Wire it into your agent

Shantytown provisions role instructions and hooks for the selected harness.
It works with Quipu for shared work and memory, Seeds for Quipu-backed tasks,
Bobbin for code context, and Yupana for structural checks. Camayoc prepares
knowledge for Quipu; Desire Path can turn recurring agent mistakes into requests.
Caboodle installs reviewed tool versions. Chaski reactions and Shuttle workflows
can supply external event-driven work. These integrations are optional and need
[configuration](https://scbrown.github.io/shantytown/integrations.html).

## Before you start

- Use Linux or macOS with `tmux`, Python 3.11+ and an authenticated agent CLI.
- Choose the tracker and registry that fit your project; Quipu is an optional backend.
- Configure the host scheduler to call `st fleet tend` for recurring work.
  Jobs run on a pass, within its cadence, rather than at an exact second.
- Review credentials, account limits and approval mode before unattended work.

## What's next

- [Book home](https://scbrown.github.io/shantytown/)
- [Documentation map](https://scbrown.github.io/shantytown/map.html)
- [Getting started](https://scbrown.github.io/shantytown/getting-started.html)

## 🧺 The stack

<!-- stack-table:start -->

The Quipu stack is built around a governed, bitemporal knowledge store: shared
facts, decisions and work history your agents can query. Quipu can check writes
against your rules, records where each fact came from, and answers what was true
when.

| tool | what it gives your agents |
|---|---|
| [caboodle](https://github.com/scbrown/caboodle) | 🧰 Agent Platform Toolkit - installs and configures the quipu stack |
| [quipu](https://github.com/scbrown/quipu) | stores shared facts with provenance and history; can check writes against your rules |
| [camayoc](https://github.com/scbrown/camayoc) | prepares knowledge and vocabulary for Quipu, with checks before it is admitted |
| [bobbin](https://github.com/scbrown/bobbin) | searches your code and can include related knowledge from Quipu |
| [yupana](https://github.com/scbrown/yupana) | shows code impact and can read policies from Quipu to check changes |
| [desire-path](https://github.com/scbrown/desire-path) | turns agent mistakes into feature requests; works on its own without Quipu |
| [seeds](https://github.com/scbrown/seeds) | a work item tracker backed by the Quipu knowledge base |
| [shantytown](https://github.com/scbrown/shantytown) | runs crews of AI agents on work items, triggered by hand, on a schedule or by events; can share work and memory through Quipu |
| [rikuy](https://github.com/scbrown/rikuy) | live brief: status, graphs, watches and signed decisions over Quipu |
| [shuttle](https://github.com/scbrown/shuttle) | runs signed agent workflows and keeps their records in Quipu |

<!-- stack-table:end -->

## Contributing

```sh
python3 -m pytest -q
```

Read [CONTRIBUTING.md](CONTRIBUTING.md) for conventions and validation.

## 📜 License

[Apache-2.0](LICENSE)
