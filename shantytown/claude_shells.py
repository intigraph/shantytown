"""Claude Code background-shell count read from the process tree.

WHY THIS EXISTS (hammond, 2026-11-06). Claude's footer prints "N shell(s)" only
when the line fits. tmux's `window-size latest` follows the last client that
attached, so a narrow attach cuts the footer with "…" and the footer reader can
no longer see zero. unattended_shell_block then refused, correctly, but forever:
hammond's own self-cycle request sat refused for 50+ minutes (11 waiter polls,
then every 5-minute tend pass) on an idle pane with no shell running.

The runtime's children carry the same fact without depending on width. Every
Bash tool call Claude Code runs is a direct child shell whose argv sources
`~/.claude/shell-snapshots/snapshot-*`. On an idle pane no foreground call is
running, so the snapshot shells still alive are the background ones.

None means "could not look", never zero: no pane pid, no single claude runtime
under the pane, an argv missing for any listed pid, or ps/pgrep failed. Callers keep refusing on None.
"""
from __future__ import annotations

import os
import subprocess
import sys

SNAPSHOT_MARK = "/shell-snapshots/snapshot-"
_MAX_CHILDREN = 256


def _children(pid: str) -> list[str] | None:
    # BSD pgrep hides its caller's ancestors unless -a; the agent asking about
    # itself is our ancestor during its own tool call.
    argv = ["pgrep", "-a", "-P", pid] if sys.platform == "darwin" else ["pgrep", "-P", pid]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode not in (0, 1):          # 1 = no children, a real answer
        return None
    pids = r.stdout.split()
    if len(pids) > _MAX_CHILDREN or any(not p.isdecimal() for p in pids):
        return None
    return pids


def _args(pids: list[str]) -> dict[str, str] | None:
    if not pids:
        return {}
    try:
        r = subprocess.run(["ps", "-ww", "-o", "pid=,args=", "-p", ",".join(pids)],
                           capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode not in (0, 1):
        return None
    out = {}
    for ln in r.stdout.splitlines():
        parts = ln.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdecimal():
            out[parts[0]] = parts[1]
    return out


def _is_claude(args: str) -> bool:
    argv0 = args.split(None, 1)[0] if args.strip() else ""
    return os.path.basename(argv0) == "claude"


def count(pane_pid: "str | int | None") -> int | None:
    """Background shells owned by the claude runtime in this pane, or None."""
    if pane_pid is None or not str(pane_pid).isdecimal():
        return None
    root = str(pane_pid)
    kids = _children(root)
    if kids is None:
        return None
    args = _args([root, *kids])
    # Every pid pgrep listed must have an argv. A pid ps did not return (exited
    # in between, or a partial read) could be the runtime or a second one, so
    # an incomplete inventory cannot prove which runtime is unique (wu, ST514).
    if args is None or set(args) != {root, *kids}:
        return None
    # Two launch shapes: the pane pid IS claude, or claude is its child.
    runtimes = [p for p in [root, *kids] if _is_claude(args.get(p, ""))]
    if len(runtimes) != 1:
        return None
    shells = _children(runtimes[0])
    if shells is None:
        return None
    shell_args = _args(shells)
    if shell_args is None or len(shell_args) != len(shells):
        return None
    return sum(1 for a in shell_args.values() if SNAPSHOT_MARK in a)


def counter(panes, session: str):
    """A zero-arg reader for unattended_shell_block, bound to one pane."""
    def read() -> int | None:
        reader = getattr(panes, "pane_pid", None)
        if reader is None:
            return None
        try:
            return count(reader(session))
        except Exception:  # noqa: BLE001 — cannot tell is not zero
            return None
    return read
