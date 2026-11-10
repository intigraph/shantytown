"""Local, exact-session CLI update evidence; advice never performs a cycle."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import time


def version(value):
    """Stable numeric releases only; unknown/pre-release strings are not zero."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,9}\.[0-9]{1,9}\.[0-9]{1,9}", value):
        return None
    return tuple(int(part) for part in value.split("."))


def newer(running, installed):
    old, new = version(running), version(installed)
    return old is not None and new is not None and new > old


@dataclass(frozen=True)
class Evidence:
    session: str = ""
    running: str | None = None
    installed: str | None = None
    harness: str = "claude"

    @property
    def outdated(self):
        return bool(self.session) and newer(self.running, self.installed)

    @property
    def key(self):
        return f"{self.session}:{self.running}->{self.installed}" if self.outdated else ""

    @property
    def reason(self):
        label = "Codex" if self.harness == "codex" else "Claude Code"
        return f"{label} running {self.running}, installed {self.installed}"


def _load(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def running_version(path, session, *, not_before=None):
    """Read native top-level metadata from at most the last 256 KiB.

    Never parse user/message content or borrow another session's version. The
    newest main-thread version record must itself match the exact session.
    """
    if not path or not session:
        return None
    try:
        with Path(path).open("rb") as stream:
            stream.seek(0, 2)
            start = max(0, stream.tell() - 262144)
            stream.seek(start)
            lines = stream.read(262144).splitlines()
        if start:
            lines = lines[1:]  # first record may be partial
        for line in reversed(lines):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or row.get("isSidechain") or "version" not in row:
                continue
            if row.get("sessionId") != session:
                return None
            value = row.get("version")
            if not_before is not None:
                at = row.get("timestamp")
                if not isinstance(at, str):
                    return None
                try:
                    moment = datetime.fromisoformat(at.replace("Z", "+00:00"))
                    if moment.tzinfo is None or moment.timestamp() < not_before:
                        return None
                except (ValueError, OverflowError):
                    return None
            return value if version(value) is not None else None
    except OSError:
        pass
    return None


def installed_version(root, *, binary=None, program="claude"):
    """Bounded local --version, cached by executable identity and five-minute age.

    Claude launch uses PATH's claude. No network/latest-release query and no
    updater runs here. Codex's selected standalone path needs its own evidence.
    """
    try:
        binary = binary or shutil.which(program)
        if not binary or not Path(binary).is_absolute():
            return None
        target = Path(binary).resolve()
        stat = target.stat()
        identity = [str(target), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]
        path = Path(root) / "notify" / f"installed_{program}_version.json"
        old = _load(path)
        age = time.time() - old.get("at", 0) if type(old.get("at")) in (int, float) else -1
        if old.get("identity") == identity and 0 <= age < 300:
            value = old.get("version")
            return value if version(value) is not None else None
        result = subprocess.run([binary, "--version"], capture_output=True,
                                text=True, timeout=2)
        # Re-check identity: an update racing the probe must not pair a
        # version string with the wrong executable's cache identity.
        after = Path(binary).resolve()
        other = after.stat()
        if [str(after), other.st_dev, other.st_ino, other.st_size, other.st_mtime_ns] != identity:
            return None
        pattern = (r"codex-cli ([0-9]+\.[0-9]+\.[0-9]+)\s*" if program == "codex"
                   else r"([0-9]+\.[0-9]+\.[0-9]+) \(Claude Code\)\s*")
        match = re.fullmatch(pattern, result.stdout)
        value = match.group(1) if result.returncode == 0 and match else None
        from .files import write_json_atomic
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, dict(identity=identity, at=time.time(), version=value))
        return value
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def observe(root, card, payload, *, not_before=None):
    from .harness import name_for
    if root is None or not isinstance(payload, dict) or name_for(card, root=root) != "claude":
        return Evidence()
    session = payload.get("session_id")
    if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", session):
        return Evidence()
    running = running_version(payload.get("transcript_path"), session, not_before=not_before)
    # Missing running evidence must not spend even the cheap installed probe.
    return Evidence(session, running, installed_version(root) if running else None)


def for_agent(root, agent):
    """Use the local stats-bound exact session, never newest workspace history."""
    if not isinstance(agent, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", agent):
        return Evidence()
    try:
        from .files import FilesRegistry
        from . import session_budget, stats
        card = FilesRegistry(Path(root) / "crew").get(agent)
        from .launched import FilesLaunches
        stamps = FilesLaunches(Path(root) / "launched")
        if stamps.get(agent) is None:
            return Evidence()
        launched_at = (stamps.root / f"{agent}.json").stat().st_mtime
        from .harness import name_for
        if name_for(card, root) == "codex":
            try:
                return _codex_evidence(root, card, launched_at)
            except Exception:
                return Evidence(harness="codex")
        session = session_budget.current_session(Path(root), agent)
        if not card.workspace or not session:
            return Evidence()
        path = (Path.home() / ".claude" / "projects"
                / stats._claude_project_dir(card.workspace) / f"{session}.jsonl")
        return observe(root, card, dict(session_id=session, transcript_path=str(path)),
                       not_before=launched_at)
    except Exception:
        return Evidence()


def _codex_evidence(root, card, launched_at):
    """Use the existing owned-daemon/exact-thread binding, never newest history."""
    from . import codex_shells
    from .harness import CodexHarness
    from .provision import _codex_config
    binding = codex_shells._binding(card.name, root)
    context, _ = codex_shells._json(Path(root) / "context_budget" / f"{card.name}.json")
    payload = context["payload"]
    if payload.get("session_id") != binding["thread"]:
        return Evidence(harness="codex")
    with codex_shells._regular(Path(payload["transcript_path"])) as stream:
        first = stream.readline(65537)
    if len(first) > 65536:
        return Evidence(harness="codex")
    header = codex_shells._decode(first)
    meta = header.get("payload", {})
    if header.get("type") != "session_meta" or meta.get("id") != binding["thread"]:
        return Evidence(harness="codex")
    at = datetime.fromisoformat(meta["timestamp"].replace("Z", "+00:00"))
    if at.tzinfo is None or at.timestamp() < launched_at or version(meta.get("cli_version")) is None:
        return Evidence(harness="codex")
    if CodexHarness._remote_control(root):
        selected = _codex_config(card, root)
        if selected is None:
            return Evidence(harness="codex")
        # Reading the selected pointer is not permission to repair an updater.
        binary = selected.resolve().parent / "packages" / "standalone" / "current" / "codex"
        if not binary.is_file():
            return Evidence(harness="codex")
    else:
        binary = shutil.which("codex")
    installed = installed_version(root, binary=str(binary) if binary else None, program="codex")
    return Evidence(binding["thread"], meta["cli_version"], installed, "codex")


def message(evidence):
    return (f"RUNTIME UPDATE: {evidence.reason}. st fleet tend owns checkpointing "
            "and process replacement at the next safe idle boundary; "
            "do not interrupt active work. You may add richer notes with "
            "`st agent cycle --self --no-in-place --checkpoint-file "
            "<notes-file> --checkpoint-bead <id> --quipu-node <existing-node>`. "
            "An in-place context clear does not replace the running binary. "
            "This reminder schedules nothing; the executor still requires an idle "
            "pane with no running background work.")


def pending_cycles(root):
    """Read accepted requests without acknowledging them; None is UNKNOWN."""
    from .cycle import Requests
    try:
        value = json.loads(Requests(root).path.read_text())
        return value if isinstance(value, dict) else None
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None


def _manual_keep(root, agent):
    from . import config, cycle_advice
    signal = cycle_advice.latest(root, agent)
    cfg, error = config.load_or_default(Path(root))
    if signal is None or error:
        return False
    age = time.time() - signal.at
    return (0 <= age <= cfg.cycle_advice.signal_max_age_minutes * 60
            and (signal.decision == cycle_advice.KEEP
                 or (signal.related is not None and signal.related >= cfg.cycle_advice.keep_at)))


def emit(root, card, payload):
    """One non-executing Stop reminder per exact session/version pair."""
    try:
        if root is None:
            return False
        pending = pending_cycles(root)
        if pending is None or card.name in pending or _manual_keep(root, card.name):
            return False
        evidence = observe(root, card, payload)
        if not evidence.outdated or not re.fullmatch(r"[A-Za-z0-9_-]+", card.name):
            return False
        path = Path(root) / "notify" / f"runtime-update-{card.name}.json"
        old = _load(path)
        if old.get("reported") == evidence.key:
            return False
        from .files import write_json_atomic
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, dict(reported=evidence.key, at=time.time()))
        text = message(evidence)
        print(json.dumps(dict(decision="block", reason=text, systemMessage=text)))
        return True
    except Exception as exc:
        import sys
        print(f"runtime update UNKNOWN ({type(exc).__name__}); no cycle scheduled", file=sys.stderr)
        return False
