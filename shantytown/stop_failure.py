"""Claude API-error notification; never retries, types, or cycles a pane."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

from .safeguard import _save, _REQUEST


def classify(payload):
    # A safety refusal always wins over a coincident limit/auth error.
    if "safeguards" in payload.get("last_assistant_message", "").lower():
        return "safeguard-blocked"
    return {"rate_limit": "limited", "authentication_failed": "auth-dead"}.get(
        payload.get("error"), "stop-failure")


def _launch(root, agent):
    try:
        return str((Path(root) / "launched" / f"{agent}.json").stat().st_mtime_ns)
    except FileNotFoundError:
        return "UNKNOWN"


def state(root, agent):
    """Latest failure for this launch; a human relaunch retires its hold.

    Missing launch provenance does not clear a hold. Corrupt state holds loudly.
    This is not an after-turn stop: it never kills the process.
    """
    if root is None:
        return ""
    path = Path(root) / "stop-failures" / (hashlib.sha256(agent.encode()).hexdigest() + ".json")
    try:
        record = json.loads(path.read_text())
        if record["launch"] != _launch(root, agent):
            return ""
        return record["verdict"]
    except FileNotFoundError:
        return ""
    except (OSError, ValueError, KeyError):
        return "safeguard-blocked"


def pane_state(root, pane):
    if root is None or not (Path(root) / "stop-failures").exists():
        return ""
    from .files import FilesRegistry
    cards = FilesRegistry(Path(root) / "crew").all().exact()
    owners = [card for card in cards if card.pane == pane]
    return state(root, owners[0].name) if len(owners) == 1 else ""


def clear_recovered(root, agent):
    # A successful Stop can retire a transient API error, never a safety hold.
    if state(root, agent) != "safeguard-blocked":
        path = Path(root) / "stop-failures" / (hashlib.sha256(agent.encode()).hexdigest() + ".json")
        path.unlink(missing_ok=True)


def verify_wiring(root, agent, pane, cmdline_reader):
    """Require live --settings selection AND verified launch snapshot bytes."""
    from .launched import FilesLaunches
    from .runtime import settings_path_in_cmdline
    import shlex
    if not callable(cmdline_reader):
        return "unknown"
    try:
        cmdline = cmdline_reader(pane)
        if not cmdline:
            return "unknown"
        path = settings_path_in_cmdline(cmdline)
        if path is None:
            return "missing"
        launches = FilesLaunches(Path(root) / "launched")
        stamp = launches.get(agent)
        snapshot = launches.snapshot(agent)
        if stamp is None or snapshot is None or Path(stamp.settings).resolve() != Path(path).resolve():
            return "unknown"
        settings = json.loads(snapshot)
        for entry in settings.get("hooks", {}).get("StopFailure", []):
            if entry.get("matcher") not in (None, "", ".*"):
                continue
            for hook in entry.get("hooks", []):
                words = shlex.split(hook.get("command", ""))
                if (hook.get("type") == "command" and hook.get("async") is True
                        and "-m" in words):
                    i = words.index("-m")
                    if words[i + 1:i + 2] != ["shantytown.stop_failure"]:
                        continue
                    if "--root" in words and Path(words[words.index("--root") + 1]).resolve() == Path(root).resolve():
                        return "verified"
        return "missing"
    except (OSError, ValueError, TypeError, IndexError):
        return "unknown"


PLATE_TIMEOUT = 2.0


def _plate_snapshot(plate, agent):
    # This dependency is read-only. An unresponsive tracker must not consume
    # the async hook's entire lifetime before the durable notification exists.
    import queue
    import threading
    result = queue.Queue(maxsize=1)
    def read():
        try:
            result.put(plate(agent))
        except Exception:
            result.put((None, "?"))
    threading.Thread(target=read, daemon=True).start()
    try:
        return result.get(timeout=PLATE_TIMEOUT)
    except queue.Empty:
        return None, "?"


def capture(root, agent, payload, *, administrator, events, plate, deliver):
    """Persist payload before external reads/delivery; injected fixture seams."""
    import fcntl
    directory = Path(root) / "stop-failures"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    verdict = classify(payload)
    ids = sorted(set(_REQUEST.findall(payload.get("last_assistant_message", ""))))
    event_key = "stop-failure:" + hashlib.sha256(json.dumps(
        [agent, payload], sort_keys=True).encode()).hexdigest()
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = directory / (hashlib.sha256(agent.encode()).hexdigest() + ".json")
        # Never let a subsequent generic API error clear a safety hold.
        if state(root, agent) == "safeguard-blocked":
            verdict = "safeguard-blocked"
        record = {"kind": "stop-failure", "agent": agent, "launch": _launch(root, agent),
                  "payload": payload, "verdict": verdict, "requests": ids, "plate": "UNKNOWN"}
        _save(path, record)
        item, item_status = _plate_snapshot(plate, agent)
        record.update(plate=item, item_status=item_status)
        _save(path, record)
        detail = json.dumps({"kind": "stop-failure", "verdict": verdict, **payload}, sort_keys=True)
        events.persist(administrator, agent, "stop-failure", False, item=item,
                       item_status=item_status, detail=detail, key=event_key,
                       kind="stop-failure", error=payload.get("error", "unknown"),
                       error_details=payload.get("error_details"),
                       last_assistant_message=payload.get("last_assistant_message"))
        # Limit/auth paths are consumed by tend; all other failures also reach
        # the durable inbox, independent of the administrator's Stop hook.
        if verdict in ("limited", "auth-dead"):
            return record
        from .safeguard import notify
        def clip(value, size):
            return str(value).encode("utf-8")[:size].decode("utf-8", errors="ignore")
        text = (f"{verdict} agent={clip(agent, 32)}; error={clip(payload.get('error', 'unknown'), 40)}; "
                f"requests={','.join(ids[:2]) or 'UNKNOWN'}; plate={clip(item or 'UNKNOWN', 64)}. "
                "No automatic recovery; inspect local stop-failure event.")
        notify(root, agent, ids, event_key, text, record, deliver)
        return record


def main(argv=None):
    """Async, bounded notification hook. No model-facing output/continuation."""
    from types import SimpleNamespace
    from . import cli, stop_event
    from .events import FilesEvents
    from .files import FilesRegistry
    from .tier import find_administrator
    from .tmux import Tmux, declared_socket
    args = list(sys.argv[1:] if argv is None else argv)
    root = stop_event._root(args)
    try:
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            raise ValueError("StopFailure payload exceeds 64KiB")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("hook_event_name") != "StopFailure":
            raise ValueError("not a StopFailure payload")
        for field in ("error", "error_details", "last_assistant_message", "session_id"):
            if field != "error" and payload.get(field) is None:
                payload.pop(field, None)
            if field in payload and not isinstance(payload[field], str):
                raise ValueError(f"invalid {field}")
        # Capture only documented error fields, never transcript content/files.
        payload = {k: payload[k] for k in ("error", "error_details", "last_assistant_message", "session_id") if k in payload}
        reg = FilesRegistry(root / "crew")
        panes = Tmux(socket=declared_socket(root), root=root)
        agent = stop_event._stop_identity(reg, panes, os.environ.get("SHANTY_AGENT", ""))
        if not agent:
            raise ValueError("agent identity unavailable")
        reg.get(agent)  # exact registry identity, including outside tmux
        administrator = find_administrator(reg)
        if not administrator:
            raise ValueError("administrator UNKNOWN")
        options = SimpleNamespace(root=root, backend=None)
        inbox = cli._inbox(options, default="beads")
        def deliver(text):
            return inbox.deliver(administrator, text, frm="st-stop-failure").id
        capture(root, agent, payload, administrator=administrator,
                events=FilesEvents(root / "events"),
                plate=lambda name: stop_event._plate_of(root, name)[:2], deliver=deliver)
    except Exception as exc:
        print(f"stop-failure UNKNOWN ({type(exc).__name__}): {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
