"""The shared notifier's recipient adapter at the ORIGINAL Stop boundary.

# arming: hook — called by stop_event.haul, never an independent sender/schedule.
Reads only bounded spec metadata; never claims, ACKs, or rewrites a work item.
"""
import fcntl
import os
import stat
import tempfile
import hashlib
import json
from pathlib import Path

from . import due_brief
from .answer import Answer


def _read_receipt(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {"seen": []}
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("unsafe spec boundary receipt")
        if metadata.st_size > 1048576:
            raise ValueError("spec boundary receipt byte cap reached")
        with os.fdopen(fd, "rb", closefd=False) as source:
            payload = source.read(1048577)
        if len(payload) > 1048576:
            raise ValueError("spec boundary receipt byte cap reached")
        return json.loads(payload.decode("utf-8"))
    finally:
        os.close(fd)


def consume(root, recipient, rows, *, now=None):
    folder = Path(root) / "notify"
    if folder.is_symlink():
        raise ValueError("unsafe spec boundary folder")
    folder.mkdir(parents=True, exist_ok=True)
    lock_path = folder / ("spec-boundary-" + hashlib.sha256(recipient.encode()).hexdigest() + ".lock")
    with os.fdopen(os.open(lock_path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600),"a") as held:
        try:
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return None
        return _consume(root,recipient,rows,now=now)


def _consume(root, recipient, rows, *, now=None):
    root = Path(root)
    path = root / "notify" / ("spec-boundary-" + hashlib.sha256(recipient.encode()).hexdigest() + ".json")
    answer = rows()
    selected = [row for row in answer.exact() if not row.get("assignee")
                or row["assignee"].split("/")[-1] == recipient]
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("unsafe spec boundary receipt")
    state = _read_receipt(path)
    if set(state) != {"seen"} or not isinstance(state["seen"],list) or len(state["seen"]) >= 10000:
        raise ValueError("spec boundary receipt UNKNOWN or capped")
    for value in state["seen"]:
        if not isinstance(value,str):
            raise ValueError("spec boundary receipt identity invalid")
        decoded = json.loads(value)
        if (not isinstance(decoded,list) or len(decoded) != 2 or not isinstance(decoded[0],str)
                or type(decoded[1]) is not int or decoded[1] < 1):
            raise ValueError("spec boundary receipt generation invalid")
    seen = set(state["seen"])
    # Exclude fenced generations before the projection's three-row cap. A
    # capped prefix of already-seen rows must not starve later unacked work.
    from types import SimpleNamespace
    projected = due_brief.projected(
        SimpleNamespace(decision_rows=lambda _:Answer.complete_read(selected,how=answer.how)),
        recipient, now=now,
        seen_changes=frozenset(tuple(json.loads(value)) for value in seen))
    changes = projected.exact()["changes"]
    fresh = [row for row in changes if json.dumps([row["id"],row["version"]]) not in seen]
    if not fresh:
        return None
    lines = [f'{row["id"]} SPEC CHANGED v{row["previous"]} -> v{row["version"]} (unacked)' for row in fresh]
    body = "; ".join(lines) + ". Read the consolidated spec and sd history <id>, then st work item ack <id>."
    if len(body.encode()) > 400:
        raise ValueError("spec boundary pointer exceeds byte cap")
    # Fence before emitting: an ambiguous hook output can never repeat a wake.
    state["seen"].extend(json.dumps([row["id"],row["version"]]) for row in fresh)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w",dir=path.parent,delete=False) as output:
            temporary = output.name
            json.dump(state,output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary,path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return body


def at_boundary(root, recipient, reg):
    from .feed_check import _br_tracker
    tracker = _br_tracker(root,reg)
    from .sd import SdTracker
    if not isinstance(tracker,SdTracker):
        raise ValueError("spec boundary requires selected Seeds schema")
    owner = None if reg.get(recipient).role == "administrator" else recipient
    return consume(root,recipient,lambda:tracker.spec_rows(owner))
