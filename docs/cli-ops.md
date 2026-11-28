# Health and tooling

`st ops doctor` and `st ops provision`: what is installed, what is stale and which credentials a session needs. This page is part of [the CLI reference](cli.md).

## `st ops doctor` — the out-of-box feature

A full doctor run, or `st ops doctor quipu`, also checks write authorization
against `QUIPU_SERVER`, including with `--no-latest` (that flag skips release
lookups). It POSTs `{}` to `/episode`: authorization precedes JSON validation,
so the expected validation refusal proves access without storing an episode.
It reports `ok`, `no-token`, `bad-token`, `read-only`, `unreachable`, or
`unknown`/`unconfigured`. This checks permission to attempt writes, not successful
storage commits. Failures affect the doctor exit code (1 actionable, 2 unknown).

### Quipu credentials

Obtain a credential from the administrator of the target Quipu server over your
approved secret distribution channel. The administrator must first activate
its shared bearer or register the issued named credential on that server.
Installing a random string locally does not grant access.

The client convention is `~/.config/quipu/token`, read on every request, so
already-running sessions see provisioning and rotation. `QUIPU_AUTH_TOKEN`
(nonempty) overrides `QUIPU_AUTH_TOKEN_FILE`, which overrides the default path.
An explicit file override does not fall back to another token if unreadable.
Install an administrator-supplied file without putting its contents in shell
history or command arguments:

```sh
install -d -m 700 "$HOME/.config/quipu" && install -m 400 /secure/issued-token "$HOME/.config/quipu/token"
st ops doctor quipu --no-latest
```

For existing deployments using a different location, keep
`QUIPU_AUTH_TOKEN_FILE` pointing to it until provisioning and rotation target
the canonical path together. Do not copy credentials into a second independent
file that rotation will miss. Never commit token files or paste their contents
into logs, command arguments, issues or the knowledge graph.


`st --root "/path/to/.shanty" ops doctor --relay` checks incoming SSH environment
requirements together: `PATH` for `st` and `tmux`, `SHANTY_ROOT`, and
`SHANTY_BACKEND`. It prints one quoted shell setup recipe without changing files
or sending messages. Run it through non-interactive SSH on the receiving host;
an interactive local pass cannot prove that path. See [second-host setup](second-host.md#prove-messaging-across-the-boundary).
`--relay` is a separate read-only mode and cannot be combined with a tool name,
`--install`, or `--dry-run`.

```
$ st ops doctor
  • beads    1.0.5 installed
  • bobbin   0.3.1 installed — 0.6.0 available (STALE)
  ? quipu    present, but cannot report version (known upstream bug: --version opens a store)
  ✗ reactor  not installed
  • st       installed from ~/src/shantytown @ 41d9fc2d
```

### …and it asks the question about ITSELF

The last row is the one that was missing. doctor reported installed-vs-available for four tools and
never once about `st` — the tool that audits deployment drift was the only tool exempt from the
audit, and it is the one whose staleness silently corrupts every other row it prints.

It is not a version check: `st --version` is permanently `0.0.1`, so a check built on it could never
fail. It compares the two things that DO move — the **recorded source path** pipx would rebuild from,
and that checkout's **git HEAD** against the canonical checkout.

```
  ✗ st       `st` was installed from '~/src/shantytown-wt/alice', NOT the canonical
             checkout '~/src/shantytown'. Whatever is in that directory — including
             uncommitted work — is what the whole fleet is running, and a `pipx reinstall` will
             faithfully rebuild it. Fix: pipx install --force ~/src/shantytown
```

That is a real condition that occurred on 2026-07-20 (aegis-daoh): a deploy run as
`pipx install --force <my own worktree>` silently re-pointed the **fleet's** recorded source at one
crew member's private tree, and a later `pipx reinstall` faithfully rebuilt *that* rather than the
shared checkout somebody had just pulled. Nothing in the system could say so. Two rules, both
load-bearing:

1. **A recorded source that is not the canonical checkout is an ERROR, not a note.**
2. **It fails toward "cannot tell."** If it cannot read its own pipx metadata or git HEAD, that is
   exit 2 — never a pass. Uncertainty dominates the exit code, as everywhere else here.

Honest boundary: a green row proves the *source path and HEAD* line up. It does **not** prove the
installed **bytes** match that HEAD — pipx copied them at install time and the checkout can be pulled
forward afterwards. That needs a build stamp; until then this is a floor, not a guarantee.

**Deploying `st`:** always the canonical path explicitly, never bare `pipx reinstall` (it rebuilds
whatever path was last recorded, which is exactly how the above happened).

```
cd ~/src/shantytown && git pull
pipx install --force ~/src/shantytown
```

Detect is the product; `--install` is a flag. Three states exist to stop three lies: **absent** vs
**unknown** (quipu is present but its `--version` errors by opening a store — "I could not tell" is not
"not installed"), **installed** vs **stale** (bobbin 0.3.1 while 0.6.0 is out — the out-of-box problem
is not "missing", it's "installed and nobody knows what's there"), and detect **touches nothing**.
`--install` prefers a release binary, falls back to a source build only where there's no release
(beads), and **refuses loudly when the toolchain is missing** rather than half-installing. Never
`--break-system-packages` — this host is PEP-668, which is why `st` itself ships via pipx.

## New-host acceptance

`st ops doctor --deploy` checks local host identity, the exact graph Host node,
selected settings and capture hooks, explicit permissions, workspace directories,
Codex Remote Control prerequisites, incoming SSH exports, and each peer's return
configuration. It is read-only. Run it over SSH from both hosts to exercise both
directions. `--local` suppresses peer reads; `--json` emits a versioned snapshot.
Exit 1 means incomplete; exit 2 means an observation is unknown. See
[new-host setup](new-host.md) for the complete scaffold and repair checklist.

## `st ops provision` — register the rig's tooling

`st ops provision [agent] --json` reads the selected registry's local crew cards
and projects the deployment's Quipu MCP/skill manifest through the existing
harness adapters. Use `--root` to select a rig and `--registry` to select its
identity source. With no agent argument it equips every local crew workspace.
It never creates, starts, stops, or restarts an agent. Existing sessions pick up
registration on their next start.

For Claude, provisioning also repairs the `StopFailure` handler in the selected
role or per-agent settings file, including files emitted before that event was
added. It refreshes only the shantytown handler, preserving other settings and
operator hooks. An unreadable selected file refuses provisioning. Already-running
sessions still require their natural relaunch boundary to load the repaired hook.

Tambo owns binary installation and functional proof; this command owns harness
registration. It requires existing crew workspaces and a nonempty
`SHANTY_TOOLING_MANIFEST`. Missing crew, an unavailable graph, unresolved secrets,
or failed configuration read-back return nonzero. No local-template fallback is
accepted. The version-1 JSON receipt lists only agent names, harnesses and server
names, never endpoints or credentials. A failure after an earlier card was
provisioned can leave that earlier card updated; rerunning converges.

## Session credential refusal

Quipu registry writes require a nonempty credential selected in this order:
`QUIPU_AUTH_TOKEN` (trimmed), `QUIPU_AUTH_TOKEN_FILE`, then
`~/.config/quipu/token`. An explicit missing file does not fall back. Missing,
unreadable or rejected credentials emit one diagnostic and disable later writes
to that server for the session. Public reads remain available.

When a harness session ID is present, private refusal markers under
`$XDG_STATE_HOME/shantytown/quipu-auth` (default `~/.local/state`) carry this state
across invocations. If persistence is unavailable or there is no session ID,
the diagnostic names the process-only limitation. Repair the credential and start
a new session. `st ops doctor` reports a disabled session without resetting it;
its existing empty-episode probe tests authorization, not storage commits.
Transcript redaction covers canonical, explicit and former credential files,
including values shadowed by an environment override.
