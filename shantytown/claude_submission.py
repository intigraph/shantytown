"""Read exact native Claude consumption evidence; never submit or edit input.

Unsupported transcript layouts, queue-only records and quoted tool output are
UNKNOWN. A busy-session command needs both its native attachment and matching
absorbed-mid-turn acknowledgment, not merely a queue removal.
"""
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid

CAP = 16 * 1024 * 1024


def _decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate native field")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def _open(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("native receipt file ownership UNKNOWN")
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _json(path):
    with _open(path) as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("native metadata bound exceeded")
    value = _decode(raw)
    if not isinstance(value, dict):
        raise ValueError("native metadata is not an object")
    return value, raw


def _at(value, created):
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        at = moment.timestamp()
        return at if moment.tzinfo is not None and created <= at <= time.time() + 5 else None
    except (ValueError, OverflowError):
        return None


def _uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def native_proof(lines, text, session, created):
    """Only top-level native user input or paired command-consumption records."""
    users, enqueued, removed, attached = [], [], [], []
    for line in lines:
        try:
            row = _decode(line)
        except ValueError:
            continue
        if (not isinstance(row, dict) or row.get("sessionId") != session
                or row.get("isSidechain") or _at(row.get("timestamp"), created) is None):
            continue
        kind = row.get("type")
        if kind == "user":
            message = row.get("message") or {}
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, list) and len(content) == 1:
                block = content[0]
                content = block.get("text") if isinstance(block, dict) and block.get("type") == "text" else None
            if content == text and _uuid(row.get("uuid")):
                users.append(dict(kind="claude-native-user", session=session,
                                  uuid=row["uuid"], at=row["timestamp"]))
        elif kind == "queue-operation" and row.get("content") == text:
            if row.get("operation") == "enqueue":
                enqueued.append(row)
            elif (row.get("operation") == "remove" and row.get("reason") == "absorbed_mid_turn"
                  and _uuid(row.get("commandUuid")) and _uuid(row.get("deliveryId"))):
                removed.append(row)
        elif kind == "attachment":
            body = row.get("attachment") or {}
            if (isinstance(body, dict) and body.get("type") == "queued_command"
                    and body.get("prompt") == text and body.get("commandMode") == "prompt"
                    and body.get("humanTurn") is True and body.get("origin") == {"kind": "human"}
                    and row.get("renderedRole") == "system"
                    and _uuid(body.get("source_uuid")) and _uuid(body.get("delivery_id"))):
                attached.append((row, body))
    proofs = list(users)
    for removal in removed:
        if not any(_at(e["timestamp"], created) <= _at(removal["timestamp"], created) for e in enqueued):
            continue
        for row, body in attached:
            if (body["source_uuid"] == removal["commandUuid"]
                    and body["delivery_id"] == removal["deliveryId"]):
                proofs.append(dict(kind="claude-native-absorbed-command", session=session,
                    command_uuid=body["source_uuid"], delivery_id=body["delivery_id"], at=removal["timestamp"]))
    return proofs[0] if len(proofs) == 1 else None


def observe(root, worker, text, created):
    """Use only the current stats/hook-bound session and its owned transcript."""
    try:
        if (not root or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", worker)
                or type(created) not in (float, int) or not math.isfinite(created) or created <= 0):
            return None
        from .files import FilesRegistry
        from . import session_budget, stats
        card = FilesRegistry(Path(root) / "crew").get(worker)
        context_path = Path(root) / "context_budget" / (worker + ".json")
        context, before = _json(context_path)
        payload = context.get("payload") or {}
        if not isinstance(payload, dict):
            return None
        session = payload.get("session_id")
        if not _uuid(session) or session_budget.current_session(Path(root), worker) != session or not card.workspace:
            return None
        expected = (Path.home() / ".claude/projects" / stats._claude_project_dir(card.workspace)
                    / (session + ".jsonl"))
        if payload.get("transcript_path") != str(expected):
            return None
        with _open(expected) as stream:
            stream.seek(0, 2)
            start = max(0, stream.tell() - CAP)
            stream.seek(start)
            lines = stream.read(CAP).splitlines()
        if start:
            lines = lines[1:]
        proof = native_proof(lines, text, session, created)
        if (_json(context_path)[1] != before
                or session_budget.current_session(Path(root), worker) != session):
            return None
        if proof:
            proof["body_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        return proof
    except (OSError, ValueError, LookupError, TypeError):
        return None
