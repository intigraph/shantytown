---
name: session-retro
description: >
  Install a Stop hook that, at session wrap-up, solicits a short honest
  retrospective and files improvement issues for anything that would have made
  THIS session faster or better — work speed, token/context friction, hard-to-find
  information, environment and process gaps, and the operator's own code projects.
  Use this skill when asked to "capture session learnings", "file improvement
  ideas at the end of a session", "set up a retro hook", "harvest friction into
  issues", or when a coordinator wants continuous improvement without remembering
  to run it. The hook fires AT MOST ONCE per session (a Claude Code Stop hook
  otherwise fires every turn), fails open so it never blocks a stop, and files via
  any tracker (bd / gh / a create command) — degrading to a markdown backlog when
  none is present. Portable: shell + Python stdlib, no framework.
---

# Session Retro

At the end of a working session, the most valuable thing you can produce is a
short list of **what would have made this session easier** — filed as issues, not
left in your head. This skill installs a hook that asks for exactly that, once,
and turns the answer into tracked work.

**The whole skill is one hard problem, stated up front:**

> A Claude Code **Stop hook does not fire at session end. It fires at every turn
> boundary** — every time the agent finishes a response. A retrospective wired
> naively to Stop fires dozens of times an hour and is unusable spam. **Making it
> fire once per session is the entire difference between a useful skill and an
> annoyance.** Everything below is built around that.

**Stack tools this reaches for**

| Present | This skill uses it for | Absent — what happens |
|---|---|---|
| a tracker: `bd` / `gh` / a create command | improvement ideas become **filed issues** you can schedule and close | degrades to a **markdown backlog** file — captured, not lost |
| **[dispatch-work](../dispatch-work/SKILL.md)** | hand a filed improvement straight to a worker to actually fix | the issue waits in the tracker for someone to pick up |
| **[quipu](../quipu/SKILL.md)** graph | note recurring friction so the same gap isn't re-filed every session | you may file the same idea twice across sessions |
| **[desirepath](https://github.com/scbrown/desire-path)** (`dp`) | surface the FAILED tool calls it recorded — a capability reached for that didn't exist is a ready-made improvement issue | the retro asks from memory only; no pre-identified gaps |

Only two files, both stdlib Python:

- **`retro_hook.py`** — the Stop hook. De-dups and emits the retro prompt.
- **`file_improvement.py`** — files one issue, backend-pluggable (the model calls
  it, or files with its own tracker directly).

## How it solves "every turn vs session end"

There is no "session ended" event to hook. So instead of detecting session end,
the hook **fires the retro at most once and makes every later Stop a no-op**,
using two independent guards:

1. **`stop_hook_active`** — Claude Code sets this flag `true` on the Stop that was
   itself caused by a previous *blocking* hook. When we fire the retro we block
   the stop (that's how we inject the prompt); the very next Stop therefore
   arrives with `stop_hook_active: true`, and the hook exits immediately. This
   also structurally prevents an infinite block-loop.

2. **A per-session marker file** — `stop_hook_active` resets to `false` on later,
   unrelated stops in the same session, so it alone is not enough. The hook also
   writes `\<state-dir\>/session-\<session_id\>.done` the first time it fires; every
   subsequent Stop in that session sees the marker and no-ops. This is the durable
   guard. (No `session_id` in the payload? It falls back to a per-**day** marker
   so it still de-dups instead of firing per turn.)

The marker is written **before** the prompt is emitted, so even a crash mid-emit
leaves the session marked and can't cause a re-fire. The state dir is `mkdir -p`'d
on every run, so a missing dir on first use is normal, not an error.

Optional third guard — a cross-session rate limit — via `RETRO_MIN_INTERVAL_HOURS`
(e.g. `6` = at most one retro every six hours no matter how many sessions start).

```text
Stop fires  ─▶  stop_hook_active? ─yes▶ exit 0 (mid-retro, don't loop)
                     │no
                     ▼
              session marker exists? ─yes▶ exit 0 (already did this session)
                     │no
                     ▼
              within RETRO_MIN_INTERVAL_HOURS? ─yes▶ exit 0
                     │no
                     ▼
              write marker  ─▶  emit {"decision":"block","reason": <retro prompt>}  ─▶  exit 0
                                 (the model runs the retro & files issues on its next turn)
```

## It must fail open — always

**A retro hook that wedges an agent's stop is worse than no retro.** So every
error path — malformed stdin, missing keys, an unwritable state dir, any exception
at all — ends in `exit 0` with **no output**, which lets the stop proceed
normally. The hook only ever *blocks* on the single deliberate, de-duplicated fire
path. If it can't even write its marker (so it can't guarantee once-per-session),
it chooses to stay silent rather than risk firing every turn. That is the correct
bias: a missed retro costs nothing; a wedged stop costs the session.

## Install

Copy the skill, then register the hook in your agent's settings so **Stop** runs
it. In Claude Code that's `~/.claude/settings.json` (or a project
`.claude/settings.json`):

```jsonc
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/session-retro/retro_hook.py || true"
          }
        ]
      }
    ]
  }
}
```

The `|| true` is a second belt to the script's own fail-open: even if `python3`
is missing or the file path is wrong, the hook exits 0 and the stop is never
blocked. Point the path at wherever you copied the skill.

**Verify registration** without waiting for a real session: feed the hook a fake
Stop payload and confirm it fires exactly once, then no-ops:

```bash
cd ~/.claude/skills/session-retro
export RETRO_STATE_DIR=$(mktemp -d)
echo '{"session_id":"demo","stop_hook_active":false}' | python3 retro_hook.py   # prints a block JSON
echo '{"session_id":"demo","stop_hook_active":false}' | python3 retro_hook.py   # prints NOTHING (marker hit)
echo '{"session_id":"demo","stop_hook_active":true}'  | python3 retro_hook.py   # prints NOTHING (guard 1)
```

First call emits `{"decision":"block","reason":"..."}`; the second and third emit
nothing and exit 0. That contrast **is** the skill working.

## What it asks for

When it fires, the model gets a prompt to (1) write 2–4 honest sentences on what
slowed the session, then (2) **file an issue per improvement** across these areas
— skipping any that don't apply:

- **session speed / throughput** — what made you slow, what you had to redo
- **token & context friction** — what burned context or got re-read/re-explained
- **information accessibility** — a fact or doc that was hard to find or absent
- **environment & process** — tooling gaps, flaky steps, missing automation, unclear runbooks
- **the operator's own code projects** you touched

Each issue uses a fixed shape, so they're actionable rather than vague gripes:

```text
Title: <imperative, specific — "Cache the schema so it isn't re-fetched per run">
What slowed me down: <the concrete friction you hit this session>
Proposed fix: <the smallest change that removes it>
Where: <which repo / system / doc it belongs to>
```

An empty retro is a valid retro — the prompt explicitly says to file nothing and
say so if nothing rose to the bar. A padded backlog is its own kind of spam.

Override the prompt wholesale with `RETRO_PROMPT_FILE=/path/to/prompt.txt`.

## Filing — backend-pluggable, degrades to markdown

The model files issues either with its own tracker directly, or via the bundled
`file_improvement.py`, which mirrors [dispatch-work](../dispatch-work/SKILL.md)'s
create backends — the tool never needs to know what a "bead" or "issue" is, only
`create(title, body) -> id`:

```bash
# auto: bd if present, else gh, else a markdown backlog file — never loses the idea
python3 file_improvement.py "Cache the schema so it isn't re-fetched per run" \
  --body $'What slowed me down: re-fetched the schema 6x.\nProposed fix: cache it 1h.\nWhere: the graph client.'

python3 file_improvement.py "Title" --backend gh          # RETRO_GH_REPO, honours GH_HOST
python3 file_improvement.py "Title" --backend file        # RETRO_BACKLOG_DIR markdown
echo "$BODY" | python3 file_improvement.py "Title"        # body via stdin
```

Exit `0` prints the new id/path; non-zero prints `NOT FILED (<backend>): <why>` —
it never reports a filing it didn't do.

## Configure (config, not constants)

```bash
# --- the hook (retro_hook.py) ---
export RETRO_STATE_DIR=~/.cache/session-retro   # where markers live (default this)
export RETRO_MIN_INTERVAL_HOURS=0               # >0 = also cap to one retro per N hours
export RETRO_PROMPT_FILE=/path/to/prompt.txt    # replace the retro prompt entirely
export RETRO_DISABLE=1                           # turn the hook off without editing settings

# --- filing (file_improvement.py) ---
export RETRO_BACKEND=auto        # auto | beads | gh | file | cmd
export RETRO_BEADS_REPO=/path    # bd -C <repo>  (falls back to BEADS_DB)
export RETRO_GH_REPO=owner/name  # gh --repo     (set GH_HOST for a non-github forge)
export RETRO_BACKLOG_DIR=./retro # where --backend file writes markdown
export RETRO_CREATE_CMD='jira new "{title}" --desc "{body}"'   # any tracker; must print the id
```

## Prove it can fail

The property that matters is **once per session**, and it is unit-tested — run it
and watch the de-dup actually engage:

```bash
python3 -m unittest    # in this skill's directory
```

To see the failure mode this skill exists to prevent, remove the marker guard in
your head: without it, the third command in the Install verification above would
*also* print a block, and so would every Stop after it — a retro on every turn.
The test asserts the second call is silent; that assertion is the whole skill.

## Anti-patterns

- **Wiring a retro to Stop without de-dup** — the default failure. Fires every
  turn. This skill's marker file is the fix; don't remove it.
- **Blocking the stop on error** — never. The hook fails open; keep it that way.
- **Filing vague gripes** — "things were slow" is not an issue. Use the four-line
  shape: what slowed me down, proposed fix, where.
- **Padding the backlog** — an empty retro beats an invented one. Filing nothing
  is a valid outcome.
- **Reporting a filing you didn't do** — `file_improvement.py` exits non-zero and
  says `NOT FILED` rather than pretend. Trust the exit code.
