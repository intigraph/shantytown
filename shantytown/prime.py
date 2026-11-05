"""Stack orientation; the live probe reuses anchor's startup read, without publication."""
from __future__ import annotations

import argparse
import contextlib
from importlib.resources import files
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time

from . import __version__

DEADLINE = 0.65
INPUT_CAP = 16 * 1024
OUTPUT_CAP = 64 * 1024
MEMBER_CAP = 20


def primer() -> str:
    return files("shantytown").joinpath("primer.md").read_text(encoding="utf-8")


def sections(text: str) -> list[str]:
    return [line[3:] for line in text.splitlines() if line.startswith("## ")]


def select(text: str, name: str | None) -> str:
    if name is None:
        return text
    names = sections(text)
    matches = [s for s in names if s.casefold().startswith(name.strip().casefold())]
    exact = [s for s in names if s.casefold() == name.strip().casefold()]
    matches = exact or matches
    if not name.strip() or len(matches) != 1:
        raise ValueError("unknown or ambiguous section; choose: " + ", ".join(names))
    start = text.index("## " + matches[0] + "\n")
    end = text.find("\n## ", start + 1)
    return text[start:] if end < 0 else text[start:end + 1]


def empty_summary(root=None) -> dict:
    return {"root": root, "crew": None, "anchor": None, "lead": None,
            "administrator": None}


def live_snapshot(a) -> dict:
    """Use the same adapters, identity admission and anchor resolver as session start."""
    from . import cli
    from .actor_identity import authenticated_actor
    from .deployment import command_environment, resolve_root
    from .seeds_read_cache import direct_reads

    a.root, a.root_how = resolve_root(a.root)
    summary = empty_summary(str(a.root))
    if not a.root.is_dir():
        return {"status": "absent", "summary": summary, "hint": "Run `st ops doctor`."}
    from .config import load_or_default
    _cfg, error = load_or_default(a.root)
    if error:
        raise ValueError("deployment configuration unreadable")
    with command_environment(a.root, a.root_how, refresh_config=False), direct_reads():
        # Same admission as ordinary st reads. A failure never selects another identity.
        authenticated_actor()
        a.registry = cli._registry_choice(a)
        me = cli._me(a)
        if not me:
            return {"status": "absent", "summary": summary,
                    "hint": "Run `st prime <agent>` or set SHANTY_AGENT."}
        anchored, _tracker, registry = cli._resolve_anchor(a, me, require_complete=True)
        crew = registry.all().exact()
        item = anchored.item
        summary.update({
            "crew": {"total": len(crew), "members": [
                {"name": c.name[:160], "role": c.role[:80], "host": c.host}
                for c in sorted(crew, key=lambda c: c.name)[:MEMBER_CAP]],
                "truncated": len(crew) > MEMBER_CAP},
            "anchor": {"agent": anchored.me.name, "role": anchored.me.role,
                       "host": anchored.me.host, "harness": anchored.harness or None,
                       "current_work": None if item is None else {
                           "id": item.id, "title": item.title[:240],
                           "status": item.status, "priority": item.priority}},
            "lead": None if anchored.lead is None else {
                "agent": anchored.lead.name, "role": anchored.lead.role,
                "reachable": anchored.lead_up,
                "detail": anchored.lead_detail[:240] or None},
            "administrator": anchored.admin,
        })
    return {"status": "ok", "summary": summary}


def _worker() -> int:
    # The parent sends only explicit routing choices, never credential values.
    raw = sys.stdin.buffer.read(INPUT_CAP + 1)
    if len(raw) > INPUT_CAP:
        return 2
    payload = json.loads(raw)
    keys = {"root", "registry", "backend", "repo", "me"}
    if not isinstance(payload, dict) or set(payload) != keys or any(
            value is not None and not isinstance(value, str) for value in payload.values()):
        return 2
    a = argparse.Namespace(**payload)
    a.root = Path(a.root) if a.root else None
    try:
        # Adapter diagnostics must not enter the protocol or disclose credentials.
        with contextlib.redirect_stdout(sys.stderr):
            result = live_snapshot(a)
    except (Exception, SystemExit) as exc:
        from .anchor import Unreachable
        from .quipu import QuipuUnreachable
        status = ("unreachable" if isinstance(exc, (Unreachable, QuipuUnreachable,
                                                       ConnectionError, TimeoutError))
                  else "absent" if isinstance(exc, LookupError) else "unreadable")
        result = {"status": status, "summary": empty_summary(str(a.root) if a.root else None),
                  "reason": type(exc).__name__, "hint": "Run `st anchor <agent>` and `st ops doctor`."}
    encoded = json.dumps(result).encode()
    if len(encoded) > OUTPUT_CAP:
        return 2
    sys.stdout.buffer.write(encoded)
    return 0


def probe(a) -> dict:
    """Bound the whole live read, including subprocess adapters; no temp files or writes."""
    started = time.monotonic()
    root = str(a.root) if a.root is not None else None
    result = {"status": "unreadable", "summary": empty_summary(root),
              "hint": "Run `st anchor <agent>` and `st ops doctor`."}
    payload = json.dumps({key: str(getattr(a, key)) if getattr(a, key, None) is not None
                          else None for key in ("root", "registry", "backend", "repo", "me")}).encode()
    if len(payload) > INPUT_CAP:
        return {**result, "elapsed_ms": 0, "reason": "input cap"}
    proc = None
    reader = None
    try:
        proc = subprocess.Popen([sys.executable, "-B", "-m", "shantytown.prime", "--worker"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        responses = queue.Queue(maxsize=1)

        def exchange():
            try:
                with proc.stdin, proc.stdout:
                    proc.stdin.write(payload)
                    proc.stdin.close()
                    raw = proc.stdout.read(OUTPUT_CAP + 1)
                responses.put(raw)
            except OSError:
                responses.put(b"")

        reader = threading.Thread(target=exchange, daemon=True)
        reader.start()
        remaining = max(0, DEADLINE - (time.monotonic() - started))
        raw = responses.get(timeout=remaining)
        if len(raw) <= OUTPUT_CAP:
            value = json.loads(raw)
            if (isinstance(value, dict) and value.get("status") in
                    {"ok", "partial", "absent", "unreachable", "unreadable"}
                    and isinstance(value.get("summary"), dict)
                    and empty_summary().keys() <= value["summary"].keys()):
                result = value
    except queue.Empty:
        result.update(status="partial", reason="live deadline")
    except (OSError, ValueError):
        pass
    finally:
        if proc is not None:
            # Read adapters may have children (sd/tmux). Reap the complete probe
            # group so timing out cannot leave those local readers behind.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                # macOS can report EPERM for a group whose worker already exited.
                pass
            proc.wait()
        if reader is not None:
            reader.join(timeout=0.05)
    result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return result


def brief(text: str, live: dict) -> str:
    lines = [f"st {__version__}: Shantytown coordinates coding agents and their work."]
    if live["status"] == "skipped":
        lines += [line for line in select(text, "What").splitlines()
                  if line and not line.startswith("#")][:5]
    else:
        summary = live["summary"]
        lines += [f"Live state: {live['status']}. Root: {json.dumps(summary['root'])}.",
                  "Crew: " + (str(summary["crew"]["total"]) + " registered cards."
                              if summary["crew"] is not None else "unknown."),
                  "My anchor: " + json.dumps(summary["anchor"]) + ".",
                  "Lead: " + json.dumps(summary["lead"]) + "."]
    lines.append("Run `st prime` for the full primer.")
    return "\n".join(lines)


def command(a) -> int:
    text = primer()
    try:
        selected = select(text, a.section)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    live = ({"status": "skipped", "elapsed_ms": 0, "summary": empty_summary()}
            if a.static or a.section is not None else probe(a))
    envelope = {"schema": "stack-prime/1", "tool": "st", "version": __version__,
                "primer": {"sections": sections(text)}, "live": live,
                "status": "ok" if live["status"] in {"ok", "skipped"} else "degraded"}
    if not a.brief:
        envelope["primer"]["text"] = selected
    if a.json:
        print(json.dumps(envelope))
    elif a.brief:
        print(brief(text, live))
    else:
        print(selected.rstrip())
        if live["status"] != "skipped":
            print("\n## Live state\n")
            print(json.dumps(live, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_worker() if sys.argv[1:] == ["--worker"] else 2)
