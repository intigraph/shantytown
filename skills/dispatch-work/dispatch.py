#!/usr/bin/env python3
"""dispatch-work — hand a work item to another agent, honestly.

The whole pattern in three steps:

    1. CREATE the work item in whatever tracker you use   -> an id
    2. SEND the agent a message: "go read <id>"           -> tmux send-keys
    3. the agent fetches it itself

Step 2 is the only hard part, and it is hard for one reason: an agent's tmux
pane is not always ready to receive. It may be mid-response (sending interrupts
it), context-exhausted (it will read your message through a fog), or dead (the
session is gone and your keystrokes land nowhere). Sending blind is how you come
to believe work was assigned when it wasn't.

So this tool does SEND -> VERIFY -> (you record) in that order, and it TRIAGES
the pane before it sends. Every decision carries the inputs it judged on, because
a confident heuristic you cannot inspect is worse than no heuristic.

Stdlib only. The only external dependency is `tmux`. Backends (step 1) are
pluggable and optional — see `create`.

Exit codes (so a caller can branch without parsing prose):
    0  did what it said (sent + confirmed, or a read-only report)
    1  usage / precondition error (no such pane, bad args)
    2  SENT but could NOT confirm it landed — record nothing, re-dispatch
    3  REFUSED to send: the pane is not ready (mid-flight / wedged / needs reset)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum

# --- config, not constants. A skill that hardcodes a number is ours, not yours.
# Override any of these from the environment.
CONTEXT_HIGH_K = float(os.environ.get("DISPATCH_CONTEXT_HIGH_K", "400"))
TAIL_LINES = int(os.environ.get("DISPATCH_TAIL_LINES", "8"))
UNRELATED_THRESHOLD = float(os.environ.get("DISPATCH_UNRELATED_THRESHOLD", "0.15"))
TMUX = os.environ.get("DISPATCH_TMUX", "tmux")


# ---------------------------------------------------------------------------
# tmux — the transport. Every op is one subprocess call.
# ---------------------------------------------------------------------------

def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([TMUX, *args], capture_output=True, text=True)


def pane_exists(target: str) -> bool:
    # capture-pane returns non-zero for a target that isn't there. That is our
    # existence check — no session means nowhere to send.
    return _tmux("capture-pane", "-p", "-t", target).returncode == 0


def pane_capture(target: str) -> str:
    # No -S: the VISIBLE pane only. The chrome an agent runtime paints (its
    # spinner, its "/clear to save …" hint) lives on the visible pane, and that
    # chrome is what triage reads. Do not widen this to scrollback (see below).
    r = _tmux("capture-pane", "-p", "-t", target)
    return r.stdout if r.returncode == 0 else ""


def pane_send(target: str, text: str) -> None:
    # -l sends the text literally (no key-name interpretation), then a separate
    # Enter submits it. Two calls on purpose: a newline embedded in -l would not
    # submit reliably across tmux versions.
    _tmux("send-keys", "-t", target, "-l", text)
    _tmux("send-keys", "-t", target, "Enter")


# ---------------------------------------------------------------------------
# triage — the part worth packaging. Everything else is plumbing.
#
# Every rule here is encoded knowledge from running a fleet of agents. The
# design constraint that outranks accuracy: DO NOT SHIP A CONFIDENT HEURISTIC
# YOU CANNOT INSPECT. Every Decision carries its inputs so an operator sees why.
# ---------------------------------------------------------------------------

class Action(Enum):
    NUDGE = "nudge"       # healthy — send it
    REFUSE = "refuse"     # in-flight work; sending would interrupt it
    CLEAR = "clear"       # high context, unrelated — clear the agent before sending
    RESTART = "restart"   # no session, or wedged — relaunch it (see the trap below)


@dataclass
class Decision:
    action: Action
    why: str
    inputs: dict = field(default_factory=dict)

    def render(self) -> str:
        ins = " ".join(f"{k}={v!r}" for k, v in sorted(self.inputs.items()))
        return f"{self.action.value.upper():8} {self.why}\n         inputs: {ins}"


# A wedge is the SESSION being dead, not the agent printing something ugly.
# A traceback is NOT a wedge marker: agents print tracebacks constantly (a
# failing test prints one), and a healthy agent that printed a ZeroDivisionError
# and then said "I'll fix that now" must not be classified as dead and killed.
# These markers mean the process itself is gone.
WEDGED_MARKERS = ("[Process completed]", "^C^C")

# Markers that an agent is actively working. These are examples from Claude
# Code's footer; add your runtime's own "busy" chrome via DISPATCH_INFLIGHT.
INFLIGHT_MARKERS = tuple(
    m for m in os.environ.get(
        "DISPATCH_INFLIGHT", "esc to interrupt|Running…|Running...|tokens · esc"
    ).split("|") if m
)

# Claude Code offers "/clear to save 737.6k tokens" when context is worth
# clearing, and it reports the number. We read that, not a line count — see
# context_high().
_CTX_HINT = re.compile(r"/clear to save ([0-9.]+)k tokens")


def _tail(screen: str, n: int = TAIL_LINES) -> str:
    # Judge on the TAIL only. A marker in scrollback is an agent TALKING about a
    # state, not being in it — and this very file contains every marker string.
    return "\n".join(screen.splitlines()[-n:])


def looks_wedged(screen: str) -> bool:
    return any(m in _tail(screen) for m in WEDGED_MARKERS)


def mid_flight(screen: str) -> bool:
    return any(m in _tail(screen) for m in INFLIGHT_MARKERS)


def context_tokens_k(screen: str):
    # None = UNKNOWN, never "low". While a turn is in flight the spinner replaces
    # the footer, so the number is simply not visible. A caller must not read
    # None as a green light — which is safe here because mid_flight is checked
    # first.
    m = _CTX_HINT.search(screen)
    return float(m.group(1)) if m else None


def context_high(screen: str, limit_k: float = CONTEXT_HIGH_K) -> bool:
    # Ask the runtime; do NOT proxy on screen line count. `capture-pane -p`
    # returns only the visible pane (~24 lines), so a "lines > 400" proxy is
    # structurally incapable of ever firing — a third outcome painted on a
    # two-outcome coin. Reading the runtime's own token count actually fires.
    tokens = context_tokens_k(screen)
    return tokens is not None and tokens >= limit_k


def unrelated(screen: str, new_work: str, threshold: float = UNRELATED_THRESHOLD) -> bool:
    # Keyword overlap. Crude and visible on purpose — tune the threshold against
    # your own dispatches. Returns False when new_work has no words to compare.
    a = {w.lower() for w in new_work.split() if len(w) > 3}
    if not a:
        return False
    b = {w.lower() for w in screen.split() if len(w) > 3}
    return (len(a & b) / len(a)) < threshold


def triage(target: str, new_work: str) -> Decision:
    """Cheapest, most certain checks first. Read-only — touches nothing."""
    if not pane_exists(target):
        return Decision(Action.RESTART, "no session", {"pane": target, "exists": False})

    screen = pane_capture(target)
    lines = len(screen.splitlines())

    if looks_wedged(screen):
        marker = next(m for m in WEDGED_MARKERS if m in _tail(screen))
        return Decision(Action.RESTART, "wedged", {"pane": target, "marker": marker})

    if mid_flight(screen):
        marker = next(m for m in INFLIGHT_MARKERS if m in _tail(screen))
        return Decision(Action.REFUSE, "in-flight work", {"pane": target, "marker": marker})

    tokens = context_tokens_k(screen)
    hi = context_high(screen)
    if hi and unrelated(screen, new_work):
        return Decision(Action.CLEAR, "high context, unrelated",
                        {"pane": target, "context_k": tokens, "limit_k": CONTEXT_HIGH_K,
                         "screen_lines": lines, "overlap": "below threshold"})

    return Decision(Action.NUDGE, "healthy",
                    {"pane": target, "context_k": tokens,
                     "screen_lines": lines, "context_high": hi})


# ---------------------------------------------------------------------------
# backends for step 1 (create). Pluggable and optional. The tool must NOT know
# what a bead / issue / file is — it needs exactly: create(title) -> id.
# If your tracker isn't here, pass --create-cmd (a shell template with {title}).
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def create_beads(title: str) -> str:
    repo = os.environ.get("DISPATCH_BEADS_REPO")
    cmd = ["bd"] + (["-C", repo] if repo else []) + ["create", title]
    r = _run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"bd create failed: {r.stderr.strip()[:160]}")
    m = re.search(r"\b([a-z][a-z0-9_]*-[a-z0-9]+)\b", r.stdout)
    if not m:
        raise RuntimeError(f"bd create gave no id: {r.stdout.strip()[:160]}")
    return m.group(1)


def create_gh(title: str) -> str:
    # Works against GitHub OR any GitHub-compatible forge via GH_HOST. Point it
    # at your own forge; do not assume public GitHub.
    repo = os.environ.get("DISPATCH_GH_REPO")
    cmd = ["gh", "issue", "create", "--title", title, "--body", ""]
    if repo:
        cmd += ["--repo", repo]
    r = _run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"gh issue create failed: {r.stderr.strip()[:160]}")
    m = re.search(r"/issues/(\d+)", r.stdout)
    if not m:
        raise RuntimeError(f"gh issue create gave no number: {r.stdout.strip()[:160]}")
    return f"#{m.group(1)}"


def create_file(title: str) -> str:
    import hashlib
    import pathlib
    root = pathlib.Path(os.environ.get("DISPATCH_FILE_DIR", "./work"))
    root.mkdir(parents=True, exist_ok=True)
    slug = hashlib.sha1(title.encode()).hexdigest()[:8]
    path = root / f"{slug}.md"
    path.write_text(f"# {title}\n")
    return str(path)


def create_cmd(title: str, template: str) -> str:
    # Escape hatch for any tracker: --create-cmd 'jira new "{title}"'. The command
    # must print the new id (last whitespace token of stdout is taken as the id).
    r = subprocess.run(template.format(title=title), shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"create-cmd failed: {r.stderr.strip()[:160]}")
    toks = r.stdout.split()
    if not toks:
        raise RuntimeError("create-cmd printed no id")
    return toks[-1]


BACKENDS = {"beads": create_beads, "gh": create_gh, "file": create_file}


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_triage(args) -> int:
    d = triage(args.pane, args.hint or "")
    print(d.render())
    return 0


def cmd_create(args) -> int:
    if args.create_cmd:
        item_id = create_cmd(args.title, args.create_cmd)
    else:
        item_id = BACKENDS[args.backend](args.title)
    print(item_id)
    return 0


def cmd_send(args) -> int:
    target, item_id = args.pane, args.item_id
    hint = args.hint or f"Work is on your hook: {item_id} — go read it."

    # OPEN-CHECK first: the item's STATE is separate from the dispatch MESSAGE, and
    # a "done" state does not retract a queued message. Dispatching a finished item
    # is how a tracker ends up lying about assigned work (and how a duplicate build
    # gets funded). If given, the check must exit 0 for the item to be live; it is
    # pluggable exactly like create — the tool stays blind to what "open" means.
    if args.open_check:
        chk = subprocess.run(args.open_check.format(id=item_id),
                             shell=True, capture_output=True, text=True)
        if chk.returncode != 0:
            print(f"refused: --open-check exited {chk.returncode} for {item_id} — "
                  f"the item is not open; not dispatching finished work", file=sys.stderr)
            return 3

    if not pane_exists(target):
        print(f"error: pane {target} does not exist", file=sys.stderr)
        return 1

    # TRIAGE before touching the pane. Only a healthy pane (NUDGE) proceeds; every
    # other outcome refuses loudly and sends nothing — no interrupted agent, no
    # half-dispatch. The refusal prints WHY, on what inputs.
    d = triage(target, hint)
    if d.action is not Action.NUDGE:
        print(d.render(), file=sys.stderr)
        print(f"refused: pane not ready ({d.action.value}); nothing sent", file=sys.stderr)
        return 3

    # SEND -> VERIFY -> then it is the caller's turn to record in_progress. The
    # order is the point: verify reads the pane back for the id we just sent. If
    # it is not there, we sent into the void — say so (exit 2) and record NOTHING,
    # so a human re-dispatches rather than a tracker lying about assigned work.
    pane_send(target, hint)
    if item_id not in pane_capture(target):
        print(f"sent {item_id} to {target} but could not confirm it landed", file=sys.stderr)
        return 2
    print(f"delivered {item_id} -> {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="dispatch", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("triage", help="read-only: what WOULD happen to this pane")
    t.add_argument("pane", help="tmux target, e.g. session:0.0")
    t.add_argument("--hint", help="the work text, for the relatedness check")
    t.set_defaults(func=cmd_triage)

    c = sub.add_parser("create", help="make a work item, print its id")
    c.add_argument("title")
    c.add_argument("--backend", choices=sorted(BACKENDS), default="file")
    c.add_argument("--create-cmd", help="shell template with {title}; prints the id")
    c.set_defaults(func=cmd_create)

    s = sub.add_parser("send", help="triage -> send -> verify a dispatch to a pane")
    s.add_argument("pane", help="tmux target, e.g. session:0.0")
    s.add_argument("item_id", help="the id the agent will go fetch")
    s.add_argument("--hint", help="override the message sent (default: go read <id>)")
    s.add_argument("--open-check", dest="open_check",
                   help="shell template (with {id}); dispatch refuses (exit 3) unless it "
                        "exits 0 — guards against dispatching a finished/closed item")
    s.set_defaults(func=cmd_send)

    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, LookupError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
