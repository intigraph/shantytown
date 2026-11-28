# 📦 Getting started

```bash
curl -fsSL https://raw.githubusercontent.com/intigraph/shantytown/main/install.sh | sh
st ops doctor            # what's installed, what's stale, what's missing
```

The installer puts `st` in `~/.local/bin`. Pinned releases, pipx and a source install are in the
[installation reference](installation-reference.md).

You need Python 3.11+, `tmux`, and at least one agent program installed and signed in: Claude Code
is the default, and [Harnesses](harnesses.md) covers Codex, OpenCode and the others. A tracker
backend is optional. The files tracker needs nothing at all; `beads`, its Rust port `br`, Seeds and
a Forgejo issue tracker plug in with `--backend` or one line of `[env]`.


## First run — `st fleet init` asks, and you have a town

```bash
st fleet init
```

A few questions, each with a default that Enter accepts: the administrator's name, worker names,
where agents should work, the startup mode, whether the admin may
[hibernate](cli-stops.md#hibernate), and whether new cards run unattended. Unattended means the agent
program's approval prompts and sandbox are bypassed; the default is no. It shows every path it would
write, waits for a yes, then creates:

```text
  crew/<name>.json                   one card per agent, each with a generated pane (st-<name>)
  settings/<role>.settings.json      the role's stop hooks
  shantytown.toml                    startup mode + hibernate policy
  events/  launched/                 the ledgers
```

Then the town runs:

```bash
st fleet start             # mode lite: the administrator ALONE
st attach            # its pane (starts it if it's down)
st crew              # who exists, who's up
```

Scripted installs skip the questions — `st fleet init -y --admin boss --crew ada,bo`. `-y` is **required**
when stdin isn't a terminal, so an init inside a script or a hook refuses instead of hanging on a
prompt. `-n` shows every path and writes nothing.

`st fleet init` refuses a store that already has cards or a config — a second init is far more likely to be
a mistyped `--root` than an intent. To add one agent to a store that exists, `st fleet roles set <name>
<role>` writes the card and its hooks in the same operation.

Joining an existing fleet from another machine? Use the [second-host setup guide](second-host.md) before syncing roles.
