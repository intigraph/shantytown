# 🤔 Why Shantytown?

Be honest about the alternatives first, because two of them are good.

**Raw tmux and a few shell scripts** is genuinely the right answer for one or two agents. Everything
here started as that. What it never grows on its own is a memory of *what state a pane is in* before
you type into it.

**[Gas Town](https://github.com/gastownhall/gastown)** is the serious tool in this space, and it
earned its size honestly: a mayor, a deacon, convoys, formulas, quotas, scheduling — a real
orchestration tier for running a real fleet. If you want a town, use the town. Shantytown does not
try to replace any of that and never will.

Shantytown's claim is *smallness where it counts*: one Python package with one dependency, no
resident daemon, no server, and a tracker you can swap in three methods. The one scheduled thing is
`st fleet tend --install`, which asks your systemd user timer (a launchd agent on macOS) to run a
one-shot `st fleet tend` pass every five minutes; nothing of shantytown's stays running between
passes. Your own recurring work is declared in Quipu for Chaski to fire ([jobs.md](jobs.md))
rather than growing a scheduler here.

It is no longer small in every sense. Since the comparison below was first written it has gained leads and an administrator, a usage governor, automatic refill of idle
agents and supervised one-job agents. What it still does not have is a broker, a bus or a database
of its own.

|  | **raw tmux + shell scripts** | **[Gas Town](https://github.com/gastownhall/gastown)** | **shantytown** |
|--|:---:|:---:|:---:|
| Dispatch work into an agent's pane | ✅ | ✅ | ✅ |
| Agent identity, roles, hierarchy | ❌ | ✅ | ✅ |
| Stop events routed up a tier | ❌ | ✅ | ✅ |
| Orchestration tier (mayor, deacon, convoys, formulas) | ❌ | ✅ | ❌ *by design* |
| Scheduling, quotas, fleet-scale ops | ❌ | ✅ | *partly:* a usage governor and session ceilings; scheduling is left to Chaski |
| Refuses to type into a busy pane | ❌ | ❌ | ✅ |
| Pluggable work tracker (files, beads, yours) | ❌ | ❌ *beads* | ✅ |
| Runs with no resident daemon (`st fleet tend` is a one-shot on a systemd timer) | ✅ | ❌ | ✅ |
| No database or data plane to stand up | ✅ | ❌ *Dolt* | ✅ |
| Third-party runtime dependencies | none | Dolt | **one** (`cryptography`) |

The ❌ in shantytown's column is the point, not an omission. If it grows convoys, formulas or a
mayor that hands out work nobody asked for, we got it wrong.

*Two rows deserve their sources. "Refuses to type into a busy pane": `gt nudge --mode immediate`
says of itself, in its own help text, "Send directly via `tmux send-keys`. Interrupts in-flight
work." "No data plane": measured — a single `gt sling --dry-run` opened 63 sequential Dolt
connections on our host. Everything else in the Gas Town column is from its own documented feature
set; if we have any of it wrong, open an issue and we'll fix the table.*


## ⚡ Measured against Gas Town

These timings were taken in July 2026, when the project started, and have not been repeated since.
The command count is the current one. The project had a gate: *time it against `gt sling`, and if it isn't dramatically faster, say so and
stop.* Here is what the gate measured.

| | `gt sling` | `st go` | |
|---|---:|---:|---|
| Commands | ~110 | **49** | *a small, deliberate fraction of the surface, by measured use* |
| dispatch (dry-run) | 51.54 s | **0.15 s** | **~344× faster** |
| dispatch (real) | > 120 s ⏱️ | **3.40 s** | **≥35× faster** |
| Dolt connections | 63 | **3** | **21× fewer** |

**Method, so you can argue with it:** one host, one data plane, one beads store, same day. `gt sling`
was timed twice and exceeded a 120-second timeout both times, so **≥35× is a floor, not a
measurement** of its true cost. Of `st go`'s 3.4 s, essentially all of it is the tracker's own
`bd update` write — shantytown's own overhead is ~0.2 s. The command-usage figure is shell history
plus every script on one fleet. Full write-up in [`docs/vision.md`](vision.md) and
[`docs/design.md`](design.md); numbers on your fleet will differ.


## 🧭 Where this fits

- **Use Gas Town** when you want the tier — convoys, formulas, scheduling, quotas, a mayor
  coordinating work you did not personally hand out. It does things shantytown does not attempt.
- **Use raw tmux** when you have one or two agents and dispatch is something you do by hand anyway.
  Honestly, that's fine.
- **Use shantytown** when you have a handful of agents, you want *create → send → fetch* with
  supervision and budget limits around it, and you would rather add a tracker than run a daemon.
- **Use both.** Nothing here conflicts with Gas Town — shantytown talks to panes and a tracker, so it
  can sit beside a fleet rather than in front of one.
