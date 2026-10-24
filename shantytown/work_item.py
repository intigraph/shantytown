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
    from .files import FilesTracker, write_json_atomic
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
            write_json_atomic(path, value)
        return rows
    raise ValueError("selected tracker does not support comments")


def _comment_body(row):
    """Read the native tracker body fields without trusting ambiguous envelopes."""
    values = [row[key] for key in ("text", "body", "content") if key in row]
    if (not values or any(not isinstance(value, str) for value in values)
            or any(value != values[0] for value in values[1:])):
        return None
    return values[0]


def command(args, tracker):
    if args.item_action == "show":
        from .sd import SdTracker
        if isinstance(tracker, SdTracker) and getattr(tracker, "quipu", None):
            from .seeds_item import read_item
            item = read_item(tracker, args.item)
        else:
            item = exact(tracker, args.item)
        return asdict(item)
    # Mutation preconditions and read-backs retain the full SDK read.
    item = exact(tracker, args.item)
    if args.item_action == "comment":
        body = _body(args.file)
        if not args.dry_run:
            _comments(tracker, item.id, body)
            if not any(_comment_body(row) == body
                       for row in _comments(tracker, item.id)):
                raise RuntimeError("comment readback unproven; write may have landed; verify exact readback before retrying")
        return {"id": item.id, "comment": "planned" if args.dry_run else "verified"}
    fields = {}
    replace_text = getattr(args, "replace_text", False)
    if replace_text and args.item_action != "update":
        raise ValueError("--replace-text requires update with a notes/description file")
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
        text_fields = {key: value for key, value in fields.items()
                       if key in ("notes", "description")}
        if replace_text and not text_fields:
            raise ValueError("--replace-text requires a notes/description file")
        from .br import BrTracker
        if isinstance(tracker, BrTracker) and not replace_text:
            for key, value in text_fields.items():
                old = getattr(item, key, None)
                if old and old != value:
                    raise ValueError(f"non-empty {key} replacement requires --replace-text; "
                                     "read back and preserve evidence before replacing")
    from .plate_capacity import active, ensure_room, assignment_lock
    owner = fields.get("assignee", item.assignee)
    prospective = asdict(item) | fields
    with assignment_lock(tracker, owner, dry_run=args.dry_run):
        if owner and ("assignee" in fields or "status" in fields):
            current = exact(tracker, item.id)
            if "assignee" not in fields and current.assignee != item.assignee:
                raise ValueError("item owner changed before admission; reread before updating")
            item = current
            prospective = asdict(item) | fields
        from .ask_visibility import refuse_deferral
        refuse_deferral(item, fields)
        if owner and active(prospective, owner):
            ensure_room(tracker, owner, item, candidate=prospective)
        if not args.dry_run:
            from .br import BrTracker
            options = {"replace_text": True} if replace_text and isinstance(tracker, BrTracker) else {}
            tracker.update(item.id, **options, **fields)
            after = exact(tracker, item.id)
            if any(getattr(after, key, None) != value for key, value in fields.items()):
                raise RuntimeError("update readback unproven; write may have landed; verify exact readback before retrying")
    return {"id": item.id, "fields": fields,
            "result": "planned" if args.dry_run else "verified"}
