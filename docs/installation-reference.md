<p align="center"><img src="https://raw.githubusercontent.com/scbrown/shantytown/main/assets/logo.svg" alt="shantytown" width="200"/></p>
<h1 align="center">shantytown</h1>
<p align="center"><em>🏭 Ship software and organize everyday work with a crew of AI agents.</em></p>
<p align="center">
<a href="https://github.com/scbrown/shantytown/blob/main/LICENSE"><img alt="Apache-2.0 license" src="https://img.shields.io/badge/license-Apache_2.0-blue"/></a>
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

Python 3.11+ and `tmux` are prerequisites.
For the shell installer, Python needs venv and pip; pipx is only needed for
the alternative below. Pin a release and choose its installation prefix on
the receiving shell:

```sh
curl -fsSL https://raw.githubusercontent.com/scbrown/shantytown/main/install.sh |
  STACK_VERSION=v0.7.1 STACK_INSTALL_ROOT="$HOME/.local" sh
export PATH="$HOME/.local/bin:$PATH"
st --version
```

Omit `STACK_VERSION` to select the latest stable release. `STACK_INSTALL_ROOT`
defaults to `~/.local`; the installer stores each release in
`share/shantytown/<tag>` under that prefix and links `bin/st` to it.
For another prefix, put that prefix's `bin` directory on `PATH`.

### Alternative: pipx

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

### Removal

For a pipx installation, run `pipx uninstall shantytown`.

For the shell installer, choose the prefix and release you installed. Remove
its command link only when it still points to that release, then remove that
release's virtual environment:

```sh
prefix="$HOME/.local"
version=v0.7.1
if [ "$(readlink "$prefix/bin/st")" = "$prefix/share/shantytown/$version/bin/st" ]; then
  rm "$prefix/bin/st"
fi
rm -r "$prefix/share/shantytown/$version"
```

Other installed releases and your project or crew configuration remain in place.

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

## Contributing

```sh
python3 -m pytest -q
```

Read [CONTRIBUTING.md](https://github.com/scbrown/shantytown/blob/main/CONTRIBUTING.md) for conventions and validation.

## 📜 License

[Apache-2.0](https://github.com/scbrown/shantytown/blob/main/LICENSE)
