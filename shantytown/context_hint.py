"""Percentage context advice through existing Stop and PostToolUse hooks.

Work ceilings withhold new work and survive idle gaps. Occupancy does neither:
compaction can lower it, and a worker mid-apply must be free to finish safely.
The only 'block' here is the model-facing feedback protocol; no auto-cycle.
"""
from __future__ import annotations

import json
import fcntl
from contextlib import contextmanager
import os
import sys
import tempfile
import time
from pathlib import Path

from . import config, context_spend as cs, session_budget as sb


def policy(root, card):
    if root is None:
        return None, None
    cfg, error = config.load_or_default(Path(root))
    # A malformed window must not turn an armed hint silently OFF.
    return (sb.ContextLimits(), str(error)) if error else (
        cfg.session_budget.context_for(card.role, card.name), None)


def _path(root, card):
    return Path(root) / "context_budget" / f"{card.name}.json"


@contextmanager
def _locked(path):
    # Stop and tool feedback share a snapshot. Keep the lock inode separate
    # from the atomically replaced JSON, and never wait on a busy hook.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def _load(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        json.dump(data, f)
        tmp = f.name
    os.replace(tmp, path)


def _reading(payload, limits, error=None, *, max_bytes=None):
    if error:
        return cs.ContextReading(cs.UNKNOWN, detail=error)
    if not payload.get("session_id"):
        return cs.ContextReading(cs.UNKNOWN, detail="Stop payload has no session_id")
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not path:
        return cs.ContextReading(cs.UNKNOWN, detail="Stop payload has no transcript_path")
    return (cs.read(path, limits.window) if max_bytes is None else
            cs.read(path, limits.window, max_bytes=max_bytes))


def _category(reading, limits):
    if reading.state != cs.MEASURED:
        return reading.state
    if reading.over(limits.hard_pct):
        return "hard"
    return "high" if reading.over(limits.threshold_pct) else "low"


def _decide(root, card, payload, reading, limits):
    from . import context_decision, cycle_advice, deployment
    command = (deployment.deployment_default(root, "SHANTY_CONTEXT_JEV_COMMAND")
               or deployment.deployment_default(root, "SHANTY_CREATE_JEV_COMMAND"))
    situation = dict(percent=reading.pct, consumed=reading.consumed,
                     window=reading.window, target_pct=limits.threshold_pct,
                     hard_pct=limits.hard_pct, work_state="unknown",
                     rebuild_cost="unknown")
    if command and not reading.over(limits.hard_pct):
        sig = cycle_advice.latest(root, card.name)
        if sig and 0 <= time.time() - sig.at <= 60 * 10:
            situation["rebuild_cost"] = dict(related=sig.related,
                next_need_k=sig.next_need_k, reason=sig.reason[:500], by=sig.by)
    result = (dict(decision="handoff", reason="Hard percentage limit; no Jev override")
              if reading.over(limits.hard_pct)
              else context_decision.judge(situation, command,
                    work=dict(root=str(root), agent=card.name, workspace=card.workspace)))
    situation = result.pop("situation", situation)
    row = dict(result, agent=card.name, session=payload.get("session_id"),
               at=time.time(), situation=situation)
    try:
        path = Path(root) / "context-decisions.jsonl"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (json.dumps(row) + "\n").encode())
        finally:
            os.close(fd)
    except OSError:
        return dict(decision="handoff", reason="Decision log unavailable; no exception granted")
    return result


def _session_start(root, card, payload):
    """Bind the hook's exact new transcript before rendering the anchor.

    A clear can precede the next usage event. Missing fresh usage is UNKNOWN;
    never retain the previous transcript's occupancy or invent a zero.
    """
    limits, error = policy(root, card)
    if limits is None or not isinstance(payload, dict):
        return
    if not payload.get("session_id") or not payload.get("transcript_path"):
        return
    reading = _reading(payload, limits, error)
    path = _path(root, card)
    old = _load(path)
    identity = {k: payload.get(k) for k in ("session_id", "transcript_path")}
    _save(path, dict(payload=identity, at=time.time(), origin="SessionStart",
                     reported=old.get("reported") if old.get("payload") == identity else None,
                     exception=old.get("exception") if old.get("payload") == identity else None,
                     emitted_at=old.get("emitted_at") if old.get("payload") == identity else None,
                     tool_nudge=old.get("tool_nudge") if old.get("payload") == identity else None,
                     state=reading.state, detail=reading.label(), ceiling=None))


def session_start(root, card, payload):
    if policy(root, card)[0] is None:
        return
    try:
        with _locked(_path(root, card)):
            _session_start(root, card, payload)
    except OSError:
        pass  # another observation is in flight; do not block launch


def emit(root, card, payload=None) -> bool:
    if policy(root, card)[0] is None:
        return False
    try:
        with _locked(_path(root, card)):
            return _emit(root, card, payload)
    except OSError:
        return False


def _emit(root, card, payload=None) -> bool:
    """Emit one JSON feedback object when soft advice or hard handoff is due.

    Called before active-anchor/role exits, so one long task and administrators
    receive the hint too. The snapshot has its own marker, never the work-budget
    marker that can prohibit haul/feed for the rest of a session.
    """
    try:
        limits, error = policy(root, card)
        if limits is None:
            return False
        if payload is None:
            try:
                payload = {} if sys.stdin.isatty() else json.load(sys.stdin)
            except (OSError, ValueError):
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        reading = _reading(payload, limits, error)
        category = _category(reading, limits)
        path = _path(root, card)
        old = _load(path)
        key = [payload.get("session_id"), payload.get("transcript_path"),
               category, limits.window, limits.threshold_pct, limits.hard_pct, error,
               limits.nudge_at, limits.repeat_seconds]
        # A below-threshold observation resets the crossing. Session/config
        # changes also re-arm; a stale marker must not silence a new session.
        early = category == "low" and reading.state == cs.MEASURED and reading.pct >= limits.nudge_at
        if early:
            category = "nudge"
            key[2] = category
        due = category != "low" and old.get("reported") != key
        if category == "nudge" and not due:
            due = time.time() - (old.get("emitted_at") or 0) >= limits.repeat_seconds
        if category == "high" and not due and not old.get("exception"):
            due = time.time() - (old.get("emitted_at") or 0) >= limits.repeat_seconds
        if category == "hard":
            due = True  # do not fall through to ordinary self-feed until handoff
        # A keep exception expires after ten minutes or five percentage points.
        # A hard crossing is a different key and cannot inherit that exception.
        previous = old.get("exception")
        previous = previous if isinstance(previous, dict) else {}
        same_session = old.get("payload") == {k: payload.get(k) for k in
                                              ("session_id", "transcript_path")}
        same_episode = same_session and old.get("reported") == key
        if category == "high" and same_episode and previous:
            due = (time.time() >= previous.get("until", 0)
                   or reading.pct >= previous.get("through_pct", 0))
        result = None
        exception = previous if same_episode and category == "high" else None
        if due and category in ("high", "hard"):
            result = _decide(root, card, payload, reading, limits)
            exception = (dict(until=time.time() + 600,
                              through_pct=min(limits.hard_pct, reading.pct + 5))
                         if result["decision"] == "continue" else None)
        snapshot = dict(payload={k: payload.get(k) for k in
                                 ("session_id", "transcript_path")},
                        at=time.time(), reported=key if category != "low" else None,
                        emitted_at=time.time() if due else old.get("emitted_at"),
                        tool_nudge=old.get("tool_nudge"),
                        state=reading.state, detail=reading.label(), exception=exception,
                        ceiling=({"measure": "context", "measured": reading.pct,
                                  "limit": limits.threshold_pct} if category in ("high", "hard") else None))
        try:
            _save(path, snapshot)
        except OSError as exc:
            print(f"context hint: cannot retain observation ({type(exc).__name__})", file=sys.stderr)
        if not due:
            return False
        if category in ("high", "hard"):
            message = (f"CONTEXT HINT: {reading.label()}; configured hint at "
                       f"{limits.threshold_pct:g}%. Write "
                       "a checkpoint, then request `st agent cycle --self --checkpoint-file "
                       "<notes-file> --checkpoint-bead <id> --quipu-node <existing-node>`. "
                       "This posts the checkpoint; do not post it separately. "
                       "Template: `st ops help handoff`. No cycle has been scheduled.")
            if category == "hard":
                message += (f" HARD HANDOFF at {limits.hard_pct:g}%: finish only the "
                            "operation needed to leave work safe, then hand off. "
                            "No Jev override; do not start further work.")
            elif result["decision"] == "continue":
                message = (f"CONTEXT EXCEPTION: {reading.label()}; {result['reason']}. "
                           "Continue only the current operation, then checkpoint and "
                           "`st agent cycle --self --checkpoint-file <notes-file>`. "
                           "Jev will be asked again in ten minutes or five percentage "
                           f"points; hard handoff at {limits.hard_pct:g}% has no override.")
            else:
                message += " Handoff decision: " + result["reason"] + "."
        elif category == "nudge":
            message = _nudge_message(reading, limits)
        else:
            message = (f"CONTEXT MEASUREMENT for {card.name}: {reading.label()}. This is not an "
                       "under-threshold reading. Check the transcript and "
                       "[session_budget] context_window configuration. "
                       "No cycle has been scheduled; work may continue.")
        if category in ("high", "hard"):
            from .handoff_text import background_tasks
            message += " " + background_tasks()
        print(json.dumps({"decision": "block", "reason": message,
                          "systemMessage": message}))
        return True
    except Exception as exc:  # a reader failure must not prevent an agent stopping
        print(f"context UNKNOWN: hint reader failed ({type(exc).__name__})", file=sys.stderr)
        return False


def crew_label(root, card) -> str | None:
    """Read the last hook's exact transcript, never guess by newest workspace file."""
    limits, error = policy(root, card)
    if limits is None:
        return None
    data = _load(_path(root, card))
    payload = data.get("payload")
    observed = data.get("at")
    if not isinstance(payload, dict) or not isinstance(observed, (int, float)):
        return "context UNKNOWN — invalid or missing Stop observation"
    current = sb.current_session(root, card.name)
    if ((data.get("origin") != "SessionStart"
         and (not current or current != payload.get("session_id")))
            or time.time() - observed > sb.STALE_AFTER_S):
        return "context UNKNOWN — no recent Stop observation for the current session"
    reading = _reading(payload, limits, error)
    category = _category(reading, limits)
    prefix = ("handoff required (context): " if category == "hard" else
              "ceiling (context), advisory: " if category == "high" else "")
    return prefix + reading.label()


def _nudge_message(reading, limits):
    timing = ("before" if reading.pct < limits.threshold_pct else "at or above")
    return (f"CONTEXT NUDGE: {reading.label()}; prepare a checkpoint now, {timing} the "
            f"{limits.threshold_pct:g}% handoff hint. Finish the current safe operation, "
            "then checkpoint and request `st agent cycle --self --checkpoint-file "
            "<notes-file> --checkpoint-bead <id> --quipu-node <existing-node>`. "
            "No cycle has been scheduled. This reminder repeats until occupancy "
            "drops or the session changes; a bounded Jev exception is not extended.")


def tool_feedback(root, agent, payload):
    """Model-visible, nonblocking PostToolUse feedback; local reads only.

    Never invokes Jev, alters a Stop exception, or schedules a cycle. Stop
    retains its own crossing marker so a tool hint cannot suppress a decision.
    """
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "PostToolUse":
        return False
    if not isinstance(agent, str) or not agent or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in agent):
        return False
    try:
        from .files import FilesRegistry
        card = FilesRegistry(Path(root) / "crew").get(agent)
        limits, error = policy(root, card)
        if limits is None or error:
            return False
        reading = _reading(payload, limits, max_bytes=2 * 1024 * 1024)
        if reading.state != cs.MEASURED:
            return False
        path = _path(root, card)
        with _locked(path):
            old = _load(path)
            mark = old.get("tool_nudge") or {}
            key = [payload.get("session_id"), payload.get("transcript_path"),
                   _category(reading, limits), limits.window, limits.nudge_at,
                   limits.threshold_pct, limits.hard_pct, limits.repeat_seconds]
            now = time.time()
            due = reading.pct >= limits.nudge_at and (
                mark.get("key") != key or now - mark.get("at", 0) >= limits.repeat_seconds
                or reading.pct >= mark.get("pct", 0) + 5)
            if reading.pct < limits.nudge_at:
                old.pop("tool_nudge", None)
            elif due:
                old["tool_nudge"] = dict(key=key, at=now, pct=reading.pct)
            _save(path, old)
        if not due:
            return False
        message = _nudge_message(reading, limits)
        if reading.over(limits.hard_pct):
            message += f" HARD HANDOFF at {limits.hard_pct:g}%: finish only what leaves work safe, then hand off; no Jev override."
        elif reading.over(limits.threshold_pct):
            message += " The handoff hint threshold has been reached; preserve any existing bounded exception."
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}}))
        return True
    except Exception as exc:
        print(f"context nudge unavailable ({type(exc).__name__})", file=sys.stderr)
        return False
