"""Backend-neutral, exact-ID work item operations; never retry a write."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re


def exact(tracker, item_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", item_id):
        raise ValueError("item ID must be an opaque identifier, not a path")
    item = tracker.get(item_id)
    if item.id != item_id:
        raise ValueError("tracker answered a different work item ID")
    return item


def _body(path):
    if path is None:
        raise ValueError("operation requires its body/reason file")
    text = Path(path).read_text()
    if not text.strip():
        raise ValueError("an evidence body must not be empty")
    return text


def _comments(tracker, item_id, body=None):
    from .br import BrTracker, append_comment, comments
    from .files import FilesTracker
    if isinstance(tracker, BrTracker):
        if body is not None:
            append_comment(tracker, item_id, body)
        return comments(tracker, item_id)
    if isinstance(tracker, FilesTracker):
        path = tracker._path(item_id)
        value = json.loads(path.read_text())
        rows = value.get("comments", [])
        if body is not None:
            rows.append({"body": body})
            value["comments"] = rows
            path.write_text(json.dumps(value, indent=2))
        return rows
    raise ValueError("selected tracker does not support comments")


def command(args, tracker):
    item = exact(tracker, args.item)
    if args.item_action == "show":
        return asdict(item)
    if args.item_action == "comment":
        body = _body(args.file)
        if not args.dry_run:
            _comments(tracker, item.id, body)
            if not any(row.get("body", row.get("content")) == body
                       for row in _comments(tracker, item.id)):
                raise RuntimeError("comment readback unproven; write may have landed, do not resend")
        return {"id": item.id, "comment": "planned" if args.dry_run else "verified"}
    fields = {}
    if args.item_action == "close":
        from .br import BrTracker
        from .files import FilesTracker
        if not isinstance(tracker, (BrTracker, FilesTracker)):
            raise ValueError("selected tracker cannot verify a close reason")
        fields = {"status": "closed", "close_reason": _body(args.reason_file).strip()}
    elif args.item_action == "update":
        for key in ("status", "assignee", "priority"):
            value = getattr(args, key, None)
            if value is not None:
                fields[key] = value
        for key in ("description", "notes"):
            path = getattr(args, key + "_file", None)
            if path:
                fields[key] = _body(path)
        if not fields:
            raise ValueError("update requires explicit fields")
        if fields.get("status") == "closed":
            raise ValueError("use close with a reason file for terminal work")
    if not args.dry_run:
        tracker.update(item.id, **fields)
        after = exact(tracker, item.id)
        if any(getattr(after, key, None) != value for key, value in fields.items()):
            raise RuntimeError("update readback unproven; write may have landed, do not resend")
    return {"id": item.id, "fields": fields,
            "result": "planned" if args.dry_run else "verified"}
