# 🖥️ See It In Action

Create work and hand it to an agent. The id is the product — it's what step two has to say.

The samples on this page are cut down to the lines that carry the point. A current release
prints more around them: a dispatch also says who it is signed as and what graph context it
carries, and the roster adds diagnostics below the table.

```text
$ st task "fix the login timeout"
  st-1    fix the login timeout

$ st go st-1 ada
  st-1 -> ada          in progress
  sent to pane st-ada
```

Every writing command has a `--dry-run`, and dispatch shows you triage's verdict before it commits
to anything:

```text
$ st go st-1 ada --dry-run
  would: tracker.update(st-1, status=in_progress, assignee=ada)
  would: send-keys -> pane st-ada
  would NOT: create a convoy, spawn a session, wait for ack

  triage: NUDGE    healthy
         inputs: context_high=False context_k=None pane='st-ada' screen_lines=24
  0 writes. 1 tracker call, 1 send-keys.
```

When the agent is mid-task, `st go` **refuses** rather than typing over its work — and it shows you
the input it judged on, so you can disagree with it:

```text
$ st go st-2 ada
  refused: pane not ready — REFUSE   in-flight work
         inputs: marker='esc to interrupt' pane='st-ada'
$ echo $?
1
```

`st crew` answers the only question a dispatcher actually has — *who can take the next item?* Each
row is the agent, its role, whether it is up, whether its settings are current, the state of its
work tree, what it is doing, its approval posture and its pane. The line under it is how full its
plate is.

```text
$ st crew

  ada         tree=worker        up            current  ok        idle             bypass  st-ada
    plate: 1/10
  bo          tree=worker        up            current  ok        busy             bypass  st-bo
    plate: 2/10
  cy          tree=lead          up            STALE    ok        idle             bypass  st-cy
    plate: 0/10
  di          tree=worker        down          —        —         —                —       st-di
    plate: 0/10

  2 free: ada, cy
  1 busy: bo

  ⚠ 1 agent(s) are running settings OLDER than the file on disk: cy
    Their hooks are whatever the file said AT LAUNCH. Rewriting a settings file is not deploying it — only a relaunch
    (`st agent stop <agent> && st agent new <agent>`) re-reads it.
```

And every session starts from the anchor — identity, standing directives, the current item, and
where your stop events go:

```text
$ st anchor ada

  You are ada — worker, reports to cy.

  DIRECTIVES
    Check governing Directives in Quipu before acting; record new operator directives verbatim as Directive entities.

  ON YOUR PLATE
    ▶ st-1  fix the login timeout        (in_progress)

  YOUR LEAD
    cy (lead) — up. Your stop events go to them.
```

A message to an agent that isn't there is **never** reported as delivered:

```text
$ st inbox di "protocol step 3"
  could not tell: pane st-di is not there (agent down?)
$ echo $?
2
```

## Cold start — one command, and only the crew you're paying for

`st fleet start` takes a **mode**, and `lite` — the default — brings up the administrator **alone**: one
agent's context, one agent's bill, and the one agent that can decide who else is needed.

```text
$ st fleet start
  mode 'lite' from the built-in defaults (no config file) — 1 agent(s): sattler

  + sattler      started      launched into 'shanty-sattler', hooks verified

  mode 'lite' · 1 selected · started 1 · 1 up · 0 fault(s)

  attach: `st attach sattler`   ·   roster: `st crew`

$ st attach                          # the admin's pane. starts it first if it's down
```

`--mode heavy` brings up every card. It is **idempotent** — `already-up` is a success, a live agent is
never launched over, and a retired one is never resurrected — so it is safe to run when you don't know
what's already running, which is the only time you need it. Modes are named crew sets in
[`shantytown.toml`](shantytown.toml.example), where the admin can also be told to
[**hibernate**](cli.md#hibernate): stop waking
itself at every turn boundary once it has handed the work out.
