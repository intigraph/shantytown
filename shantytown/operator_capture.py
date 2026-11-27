"""Operator messages captured verbatim into Quipu by st, never by someone remembering.

# arming: the administrator's UserPromptSubmit hook (runtime.operator_capture_hooks)
# and `st inbox` when the sender is the deployment's declared operator.

aegis-za4f.20. Directive capture used to be manual: one night six operator
directives were relayed to a lead to record, with wrong time labels, and the
operator asked why someone else was writing to the graph for the administrator.
So st writes the record itself, at the moment it sees the message.

Every operator message becomes ONE `a:OperatorMessage` node: the verbatim text
(rdfs:comment), the exact receive UTC, the recipient agent, the session id and
the source channel. Not every message is an instruction, so it is NOT typed
`a:Directive` until the administrator confirms it (`st work directive mark`) or links
a seed to it (`st work directive track`, `st task --directive`), which also writes
`a:trackedBy` — the predicate the existing operator-verbatim directives use.

The LOCAL SPOOL is written before any network call, so a Quipu failure never
loses the text. Its file name is the record key (receive timestamp + content
hash). A REDELIVERY is the same text to the same recipient over the same channel
within REDELIVERY_WINDOW of an already-spooled copy: it writes nothing. The
window exists because keying on the capture instant alone deduped only within
one second, and a retried hook or a resent inbox line arrives with a later clock
(review of #764). Every Quipu statement is derived from the spooled record and
is idempotent (same subject IRI, same triples), so `st work directive flush` can
retry a failed write as often as it likes.

The capture paths (the prompt hook, `st inbox`) never wait on Quipu: they spool
and hand the write to a detached `--flush`, because a synchronous /knot call
(5s timeout per statement) would delay every operator prompt behind it.

KNOWN GAPS: a pane injection that st does not prefix with "[from ...]" is
indistinguishable from the operator typing and IS captured; a Codex
administrator has no UserPromptSubmit hook here, so only its `st inbox` path
captures.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

OPERATOR_KEY = "SHANTY_OPERATOR"          # the operator's sender name in st inbox
TRACK_MINUTES_KEY = "SHANTY_DIRECTIVE_TRACK_MINUTES"
TRACK_MINUTES = 30
REDELIVERY_WINDOW = timedelta(minutes=10)
SOURCE_KIND = "operator-verbatim"         # existing vocabulary on operator directives
# Names land in Turtle as `a:<name>`. A trailing "." would close the statement
# early ("a:x. .") and the write would stay owed forever, so a name must end on
# a letter, digit or underscore.
_NAME = re.compile(r"[a-z0-9](?:[a-z0-9_.-]{0,126}[a-z0-9_])?\Z")
_KEY = re.compile(r"om-\d{8}T\d{6}Z-[0-9a-f]{16}\Z")
# st's own pane deliveries carry the attribution marker (attribution.attribute):
# "[from sattler] ...", "[from st startup] ...". Those are crew traffic, not the
# operator typing, and capturing them would bury the operator's words.
_ATTRIBUTED = re.compile(r"\s*\[from [^\]\n]{1,80}\]")


class CaptureRefused(ValueError):
    pass


def spool_dir(root) -> Path:
    return Path(root) / "operator-messages"


def _utc(when: datetime) -> datetime:
    if when.tzinfo is None:
        raise CaptureRefused("receive time must be timezone-aware")
    return when.astimezone(timezone.utc).replace(microsecond=0)


def key_for(text: str, received_at: datetime) -> str:
    stamp = _utc(received_at)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"om-{stamp:%Y%m%dT%H%M%SZ}-{digest}"


@dataclass
class Record:
    key: str
    text: str
    received_at: str
    recipient: str
    session: str
    channel: str
    directive: bool = False
    tracked_by: list[str] = field(default_factory=list)
    # Statements Quipu has accepted, by name ("message", "directive",
    # "tracked:<seed>"). Anything derived but not listed here is still owed.
    written: list[str] = field(default_factory=list)

    def owed(self) -> list[str]:
        want = ["message"] + (["directive"] if self.directive else []) \
            + [f"tracked:{seed}" for seed in self.tracked_by]
        return [w for w in want if w not in self.written]


def _path(root, key: str) -> Path:
    if not _KEY.fullmatch(key):
        raise CaptureRefused(f"not an operator message key: {key!r}")
    return spool_dir(root) / f"{key}.json"


def _save(root, record: Record) -> None:
    from .files import write_json_atomic
    write_json_atomic(_path(root, record.key), record.__dict__)


@contextmanager
def _locked(root):
    """One writer at a time over the spool: the hook, `st inbox`, a detached
    flush and the administrator's mark/track can all run at once, and a
    read-modify-write without this lets a flush save a stale copy over a mark
    that landed meanwhile, losing directive=True."""
    import fcntl
    directory = spool_dir(root)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(directory / ".lock", "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _update(root, key: str, change) -> Record:
    with _locked(root):
        record = load(root, key)
        change(record)
        _save(root, record)
        return record


def load(root, key: str) -> Record:
    try:
        data = json.loads(_path(root, key).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CaptureRefused(f"no captured operator message {key}") from None
    return Record(**data)


def records(root) -> list[Record]:
    out = []
    for path in sorted(spool_dir(root).glob("om-*.json")):
        out.append(Record(**json.loads(path.read_text(encoding="utf-8"))))
    return out


def resolve(root, ref: str) -> str:
    """A key, or a Directive IRI / a:-name ending in one (what --directive accepts)."""
    tail = ref.strip().rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    tail = tail.split(":", 1)[-1] if tail.startswith("a:") else tail
    _path(root, tail)
    return tail


def _literal(value: str) -> str:
    # JSON string escapes are a subset of Turtle's, and ensure_ascii=False keeps
    # the operator's characters as written: verbatim means byte-for-byte.
    return json.dumps(value, ensure_ascii=False)


def turtle(onto: str, record: Record, statement: str) -> str:
    s = f"a:{record.key}"
    if statement == "message":
        body = (f"{s} a a:OperatorMessage ;\n"
                f"  rdfs:label {_literal(record.key)} ;\n"
                f"  rdfs:comment {_literal(record.text)} ;\n"
                f"  a:sourceKind {_literal(SOURCE_KIND)} ;\n"
                f"  a:receivedAt {_literal(record.received_at)}^^xsd:dateTime ;\n"
                f"  a:recipient a:{record.recipient} ;\n"
                f"  a:sessionId {_literal(record.session)} ;\n"
                f"  a:sourceChannel {_literal(record.channel)} .\n")
    elif statement == "directive":
        body = f"{s} a a:Directive .\n"
    elif statement.startswith("tracked:"):
        body = f"{s} a:trackedBy a:{statement.split(':', 1)[1]} .\n"
    else:
        raise CaptureRefused(f"unknown statement {statement!r}")
    return (f"@prefix a: <{onto}> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n" + body)


def _default_writer(root):
    from .quipu import QuipuRegistry
    registry = QuipuRegistry(root=root, client_label="st-operator-capture")
    return lambda record, statement: registry._knot(turtle(registry.onto, record, statement))


def flush(root, key: str | None = None, *, writer=None) -> tuple[int, list[str]]:
    """Deliver what each spooled record still owes. Returns (written, failures).

    A failure leaves the statement owed and the text on disk; nothing here ever
    deletes a record. Error text is reduced to the exception class, because a
    remote error can carry an authority URL.
    """
    keys = [key] if key else [r.key for r in records(root)]
    write = writer
    done, failed = 0, []
    for k in keys:
        record = load(root, k)
        for statement in record.owed():
            try:
                if write is None:
                    write = _default_writer(root)
                write(record, statement)
            except Exception as error:
                failed.append(f"{record.key} {statement}: {type(error).__name__}")
                break   # keep order: never write trackedBy before the node exists

            def wrote(fresh, statement=statement):
                if statement not in fresh.written:
                    fresh.written.append(statement)
            # Reload under the lock: saving `record` itself would overwrite a
            # mark/track that landed while the write was in flight.
            _update(root, k, wrote)
            done += 1
        # A mark/track during this pass adds statements; the next flush owes them.
    return done, failed


def _redelivered(root, text: str, recipient: str, channel: str, when: datetime) -> bool:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    for path in spool_dir(root).glob(f"om-*-{digest}.json"):
        stamp = datetime.strptime(path.name[3:19], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        if abs(when - stamp) > REDELIVERY_WINDOW:
            continue
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return True   # unreadable but present: never mint a second node over it
        if (prior.get("text"), prior.get("recipient"), prior.get("channel")) == (text, recipient, channel):
            return True
    return False


def spawn_flush(root, key: str) -> None:
    """Deliver a just-spooled record without making the caller wait on Quipu."""
    subprocess.Popen(
        [sys.executable, "-m", "shantytown.operator_capture", "--root", str(Path(root)),
         "--flush", key],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True)


def capture(root, text: str, *, recipient: str, session: str, channel: str,
            received_at: datetime | None = None, writer=None,
            deliver: bool = True) -> Record | None:
    """Spool, then write. None = this message was already captured.

    deliver=False spools only; the caller hands the write to spawn_flush.
    """
    if not isinstance(text, str) or not text.strip():
        raise CaptureRefused("empty operator message")
    if not _NAME.fullmatch(recipient or ""):
        raise CaptureRefused(f"recipient is not an agent name: {recipient!r}")
    when = _utc(received_at or datetime.now(timezone.utc))
    record = Record(key=key_for(text, when), text=text,
                    received_at=f"{when:%Y-%m-%dT%H:%M:%SZ}", recipient=recipient,
                    session=str(session or ""), channel=channel)
    data = json.dumps(record.__dict__, ensure_ascii=False, indent=1).encode("utf-8")
    with _locked(root):
        if _redelivered(root, text, record.recipient, channel, when):
            return None
        try:
            # O_EXCL backs the lock: the first delivery creates the file.
            fd = os.open(_path(root, record.key), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return None
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    if deliver:
        flush(root, record.key, writer=writer)
    return load(root, record.key)


def mark(root, ref: str, *, writer=None) -> Record:
    key = resolve(root, ref)
    _update(root, key, lambda r: setattr(r, "directive", True))
    flush(root, key, writer=writer)
    return load(root, key)


def track(root, ref: str, seed: str, *, writer=None) -> Record:
    """Linking a seed is itself the confirmation that the message is a directive."""
    if not _NAME.fullmatch(seed or ""):
        raise CaptureRefused(f"not a seed id: {seed!r}")
    key = resolve(root, ref)

    def link(record):
        record.directive = True
        if seed not in record.tracked_by:
            record.tracked_by.append(seed)
    _update(root, key, link)
    flush(root, key, writer=writer)
    return load(root, key)


def track_minutes(root) -> int:
    from .deployment import deployment_default
    raw = deployment_default(root, TRACK_MINUTES_KEY)
    try:
        value = int(raw) if raw else TRACK_MINUTES
    except ValueError:
        return TRACK_MINUTES
    return value if value > 0 else TRACK_MINUTES


def notices(root, *, now: datetime | None = None) -> list[str]:
    """The administrator's notice lines; [] when there is nothing to say."""
    try:
        found = records(root)
    except FileNotFoundError:
        return []
    except Exception:
        return ["  OPERATOR MESSAGES: UNKNOWN (local spool unreadable)"]
    now = now or datetime.now(timezone.utc)
    limit = timedelta(minutes=track_minutes(root))

    def age(r):
        return now - datetime.strptime(r.received_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    lines = []
    untracked = [r.key for r in found if r.directive and not r.tracked_by and age(r) >= limit]
    if untracked:
        lines += [f"  UNTRACKED DIRECTIVES ({len(untracked)}): no seed after "
                  f"{int(limit.total_seconds() // 60)}m. `st work directive track <key> <seed>`.",
                  "    " + ", ".join(untracked[:8]) + (f" (+{len(untracked) - 8} more)" if len(untracked) > 8 else "")]
    unreviewed = [r.key for r in found if not r.directive]
    if unreviewed:
        lines += [f"  OPERATOR MESSAGES TO REVIEW ({len(unreviewed)}): "
                  "`st work directive mark <key>` if it gives an instruction.",
                  "    " + ", ".join(unreviewed[:8]) + (f" (+{len(unreviewed) - 8} more)" if len(unreviewed) > 8 else "")]
    owed = [r.key for r in found if r.owed()]
    if owed:
        lines += [f"  OPERATOR CAPTURE SPOOLED ({len(owed)}): Quipu write pending. "
                  "`st work directive flush`."]
    return lines


def hook(root, stdin_text: str, *, env=None, now=None, writer=None,
         spawn=None) -> Record | None:
    """UserPromptSubmit: the operator typing into the administrator's pane.

    Spools and returns; the Quipu write runs detached (spawn_flush) unless a
    writer is injected.
    """
    env = os.environ if env is None else env
    payload = json.loads(stdin_text or "{}")
    text = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip() or _ATTRIBUTED.match(text):
        return None
    record = capture(root, text, recipient=env.get("SHANTY_AGENT", ""),
                     session=payload.get("session_id") or env.get("CLAUDE_SESSION_ID", ""),
                     channel="pane-prompt", received_at=now, writer=writer,
                     deliver=writer is not None)
    if record is not None and writer is None:
        (spawn or spawn_flush)(root, record.key)
    return record


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="capture an operator prompt (hook)")
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--flush", metavar="KEY", help="deliver one spooled record (detached)")
    args = ap.parse_args(argv)
    try:
        if args.flush:
            flush(args.root, args.flush)
        else:
            hook(args.root, sys.stdin.read())
    except Exception as exc:  # a hook must never obstruct the operator
        print(f"operator_capture: capture UNKNOWN ({type(exc).__name__})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
