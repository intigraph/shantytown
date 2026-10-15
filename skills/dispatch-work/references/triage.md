# Triage: why each rule is shaped the way it is

Triage decides whether an agent's pane is ready to receive work. It is the only
hard part of dispatch, and every rule below is a mistake someone already made.
The theme is one idea: **do not ship a confident heuristic you cannot inspect.**
Each decision the engine returns carries the exact inputs it judged on, so when it
is wrong you can see *why* and tune it — rather than trusting or distrusting a
black box.

## The check order, and why it is that order

```
exists?  →  wedged?  →  mid-flight?  →  high-context & unrelated?  →  NUDGE
```

Cheapest and most certain first. "No session" is a boolean and outranks
everything — there is no pane to inspect. A dead process outranks a busy one.
A busy agent outranks a context judgement, because context is the fuzziest call
and you should never make it about a pane that is actively working.

## Wedged: the markers are deliberately narrow

`WEDGED_MARKERS = ("[Process completed]", "^C^C")` — and nothing else.

The obvious marker to add is a Python traceback. Don't. Agents print tracebacks
as a matter of course: a failing test prints one, a caught exception prints one,
an agent *explaining* an error pastes one. A healthy, idle agent whose pane showed
a `ZeroDivisionError` and then "I'll fix that now" was once classified as wedged
and relaunched — killing a working agent for doing its job. That is far worse than
missing a real wedge, because a real wedge is visible and recoverable while a
wrongful restart destroys in-progress work silently.

The surviving markers mean the *process* is gone, not that the agent had a bad
turn. Keep this set small; widen it only with a marker that cannot appear in
healthy output.

## Mid-flight: judge the tail, never the scrollback

An agent that is working shows its runtime's busy chrome — for Claude Code, a
footer like `esc to interrupt`. The trap: those exact strings also appear in
*scrollback*, because an agent that is reading or discussing dispatch code has the
words on its screen. A whole-screen search then reads "busy" off an idle agent
that happens to be looking at the word "busy."

So triage judges only the last few lines (`DISPATCH_TAIL_LINES`, default 8) —
where live chrome lives. A marker further up is the agent *talking about* a state,
not being in it. This file contains every marker string; an agent reading it must
not thereby look permanently busy.

## High context: ask the runtime, do not proxy on screen size

The first version of this check was `len(screen.splitlines()) > 400`. It was
honestly labelled and completely dead: `tmux capture-pane -p` returns only the
*visible* pane — about two dozen lines — so `24 > 400` is never true. The CLEAR
branch could only fire in a unit test that synthesised a 500-line screen; in
production it never fired once, for any input. A three-outcome decision was a
two-outcome coin with a third face painted on, and every call *looked* fine.

That is the worst kind of check: incapable of one of its outcomes, and green
either way. The fix is not a better proxy — it is to stop proxying. Claude Code
already counts its own context and prints `"/clear to save 737.6k tokens"` when it
is worth clearing. Read that number. It fires on real panes carrying real context.

If your runtime reports context differently, change the regex — but read a real
number, never a stand-in that cannot reach the threshold.

## Unrelated: crude and visible on purpose

CLEAR fires only when context is high **and** the new work is unrelated to what
is on the pane — because if the big context *is* the new task, clearing throws
away exactly what you want the agent to keep. "Unrelated" is keyword overlap below
a threshold: blunt, easy to read, easy to tune. A cleverer relatedness model would
be less inspectable, and inspectable beats clever here. Tune
`DISPATCH_UNRELATED_THRESHOLD` against your own dispatches.

## RESTART: relaunch, never a silent "handoff"

RESTART means relaunch the session from the launcher that starts your agents with
their full configuration. It does **not** mean any "handoff" or "cycle" command
that re-execs the agent while dropping its hooks/settings. Such a command returns
an agent that looks identical to a healthy one but has lost the wiring that makes
it drain queues, honour policies, or report state — and you will not see the
difference until something that should have fired doesn't. If your framework has a
handoff that does not re-register settings on respawn, it is not a restart; it is a
quiet downgrade. Relaunch clean.

## Why verify by the pane at all

The status field lies. An agent can be `running` and parked at a prompt, or
`running` and context-dead. The only ground truth for "did my message arrive" is
the pane itself: send, then read it back and look for the id you sent. A false
negative (the agent cleared the line before you looked) is safe — it maps to
"could not confirm," records nothing, and a human re-dispatches. A false positive
— believing a dropped send landed — is the failure this whole skill exists to
prevent, and reading the pane back is the only thing that catches it.
