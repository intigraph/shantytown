"""Optional evidence at the generator and native receiver boundaries.

# arming: library — called by the existing Stop generator/stats capture only.
No sender, ACK, retrospective reconstruction, or absence-as-failure inference.
"""
from __future__ import annotations

import hashlib
import fcntl
import json
import os
from pathlib import Path
import secrets
import stat

_CAP = 8 * 1024 * 1024
_ROWS = 256
_FIELDS = {"agent", "harness", "session", "hook_run_id", "item", "generation", "body_sha256"}


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def hook_input(stream):
    """Read only currently available hook stdin; never wait for an interactive caller."""
    import select
    try:
        fd = stream.fileno()
        if not select.select([fd], [], [], 0)[0]:
            return None
        data = os.read(fd, 16385)
        return json.loads(data) if len(data) <= 16384 else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _identity(value):
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("spec observation identity UNKNOWN")
    for key in _FIELDS - {"generation"}:
        if (not isinstance(value[key], str) or not value[key]
                or len(value[key].encode()) > 256 or any(ord(c) < 32 for c in value[key])):
            raise ValueError("spec observation identity UNKNOWN")
    if type(value["generation"]) is not int or value["generation"] < 1:
        raise ValueError("spec observation generation UNKNOWN")
    digest = value["body_sha256"]
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("spec observation digest UNKNOWN")
    return value


def _open_directory(folder, *, create=False):
    # Walk with directory descriptors so an ancestor retarget between check
    # and open cannot redirect evidence. Item/session strings never form paths.
    folder = Path(folder).absolute()
    if ".." in folder.parts:
        raise ValueError("unsafe spec observation folder")
    fd = os.open(folder.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in folder.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _directory(root, *, create=False):
    return _open_directory(Path(root) / "notify" / "spec-observation", create=create)


def _names(folder):
    names = []
    with os.scandir(folder) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > _ROWS:
                raise ValueError("spec observation evidence capped")
    return names


def _read(path, cap, *, dir_fd=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
            raise ValueError("spec observation source UNKNOWN or capped")
        with os.fdopen(fd, "rb", closefd=False) as source:
            data = source.read(cap + 1)
        if len(data) > cap:
            raise ValueError("spec observation source capped")
        return data
    finally:
        os.close(fd)


def _publish(root, value):
    data = _encoded(value)
    target = _digest(data) + ".json"
    folder = _directory(root, create=True)
    temporary = ".staged-" + secrets.token_hex(16)
    # Hard-link a complete private staging inode; never replace evidence.
    # A duplicate is idempotent, including its original mtime.
    try:
        fcntl.flock(folder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        names = _names(folder)
        if target not in names and len(names) >= _ROWS:
            raise ValueError("spec observation evidence capped")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=folder)
        with os.fdopen(fd, "wb") as staged:
            staged.write(data)
            staged.flush()
            os.fsync(staged.fileno())
            try:
                os.link(temporary, target, src_dir_fd=folder, dst_dir_fd=folder,
                        follow_symlinks=False)
            except FileExistsError:
                if _read(target, 4096, dir_fd=folder) != data:
                    raise ValueError("spec observation evidence conflict")
        os.fsync(folder)
    finally:
        try:
            os.unlink(temporary, dir_fd=folder)
        except FileNotFoundError:
            pass
        os.close(folder)


def emitted(root, agent, harness, hook, changes, body):
    """Record generated text; a successful write still says arrival UNKNOWN.

    session_id/hook_run_id must be supplied by the actual hook input. Missing
    native fields disable evidence rather than minting a timestamp-based ID.
    """
    if not isinstance(hook, dict) or hook.get("hook_event_name") != "Stop":
        return body, []
    if (not isinstance(body, str) or len(body.encode()) > 400
            or not isinstance(changes, list) or len(changes) > 3):
        raise ValueError("spec observation emission capped")
    identities = []
    for change in changes:
        identity = _identity({"agent": agent, "harness": harness,
                              "session": hook.get("session_id"),
                              "hook_run_id": hook.get("hook_run_id"),
                              "item": change["id"], "generation": change["version"],
                              "body_sha256": _digest(body.encode())})
        identities.append(identity)
    if not identities:
        return body, []
    token = _digest(_encoded(identities))
    wire = body + " [spec-observation:" + token + "]"
    if len(wire.encode()) > 512:
        return body, []
    records = [{"state": "EMITTED", "identity": identity,
                "wire_sha256": _digest(wire.encode())} for identity in identities]
    for record in records:
        _publish(root, record)
    return wire, identities


def _records(root):
    try:
        folder = _directory(root)
    except FileNotFoundError:
        return []
    try:
        fcntl.flock(folder, fcntl.LOCK_SH | fcntl.LOCK_NB)
        paths = _names(folder)
        records = []
        for path in paths:
            if path.startswith(".staged-"):
                continue
            raw = _read(path, 4096, dir_fd=folder)
            record = json.loads(raw)
            if path != _digest(raw) + ".json":
                raise ValueError("spec observation evidence identity UNKNOWN")
            _identity(record["identity"])
            if record.get("state") not in ("EMITTED", "HARNESS_OBSERVED"):
                raise ValueError("spec observation state UNKNOWN")
            if record["state"] == "EMITTED":
                digest = record.get("wire_sha256")
                if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise ValueError("spec observation wire digest UNKNOWN")
            else:
                receiver = record.get("receiver")
                if (not isinstance(receiver, dict)
                        or set(receiver) != {"source", "event_id", "turn_id", "record_ordinal", "record_sha256"}
                        or receiver["source"] != "codex-native-archive"
                        or not isinstance(receiver["event_id"], str) or not receiver["event_id"]
                        or len(receiver["event_id"].encode()) > 256
                        or not isinstance(receiver["turn_id"], str) or not receiver["turn_id"]
                        or len(receiver["turn_id"].encode()) > 256
                        or type(receiver["record_ordinal"]) is not int or receiver["record_ordinal"] < 1
                        or not isinstance(receiver["record_sha256"], str)
                        or len(receiver["record_sha256"]) != 64
                        or any(c not in "0123456789abcdef" for c in receiver["record_sha256"])):
                    raise ValueError("spec observation receiver identity UNKNOWN")
            records.append(record)
        return records
    finally:
        os.close(folder)


def observe(root, agent, payload):
    """Observe bounded Codex native accepted inputs, never stdout or ACKs.

    Only complete, session-bound archives with native message/turn IDs qualify.
    Archive ordinal/digest supplement those native IDs, never replace them.
    Other harness schemas remain unsupported/UNKNOWN until separately qualified.
    """
    session = payload.get("session_id")
    source = payload.get("transcript_path")
    if not isinstance(session, str) or not isinstance(source, str):
        return
    emissions = [r for r in _records(root) if r["state"] == "EMITTED"
                 and r["identity"]["agent"] == agent
                 and r["identity"]["harness"] == "codex"
                 and r["identity"]["session"] == session]
    if not emissions:
        return
    path = Path(source).absolute()
    if path.suffix != ".jsonl":
        return
    parent = _open_directory(path.parent)
    try:
        data = _read(path.name, _CAP, dir_fd=parent)
    finally:
        os.close(parent)
    if not data.endswith(b"\n") or data.count(b"\n") > 65536:
        return  # a partial capture is UNKNOWN, including its apparent prefix
    lines = data.splitlines()
    entries = [json.loads(line) for line in lines]
    if not entries or any(not isinstance(entry, dict) or not isinstance(entry.get("payload", {}), dict)
                          for entry in entries):
        return
    header = entries[0]
    meta = header.get("payload", {})
    if header.get("type") != "session_meta" or (meta.get("id") or meta.get("session_id")) != session:
        return
    turn = None
    for ordinal, (line, entry) in enumerate(zip(lines, entries)):
        row = entry.get("payload", {})
        if not isinstance(row, dict):
            return
        if entry.get("type") == "turn_context":
            turn = row.get("turn_id")
            continue
        if (entry.get("type") != "response_item" or row.get("type") != "message"
                or row.get("role") != "user" or not isinstance(turn, str) or not turn
                or len(turn.encode()) > 256):
            continue
        event = row.get("id")
        metadata = row.get("internal_chat_message_metadata_passthrough")
        if (not isinstance(event, str) or not event or len(event.encode()) > 256
                or not isinstance(metadata, dict) or metadata.get("turn_id") != turn):
            continue
        content = row.get("content")
        if (not isinstance(content, list) or len(content) != 1
                or not isinstance(content[0], dict) or content[0].get("type") != "input_text"
                or not isinstance(content[0].get("text"), str)):
            continue
        digest = _digest(content[0]["text"].encode())
        matches = [record["identity"] for record in emissions if record.get("wire_sha256") == digest]
        # A single notice can batch items, but two hook runs with identical
        # text are ambiguous. Never choose one by timing or list order.
        if len({identity["hook_run_id"] for identity in matches}) != 1:
            continue
        for identity in matches:
            _publish(root, {"state": "HARNESS_OBSERVED", "identity": identity,
                            "receiver": {"source": "codex-native-archive",
                                         "event_id": event, "turn_id": turn, "record_ordinal": ordinal,
                                         "record_sha256": _digest(line)}})


def show(root, identity, *, receiver=None):
    """Exact identity reader. Missing/invalid evidence is UNKNOWN, never failed."""
    try:
        _identity(identity)
        records = [record for record in _records(root) if record["identity"] == identity]
        emissions = [r for r in records if r["state"] == "EMITTED"]
        observed = [r for r in records if r["state"] == "HARNESS_OBSERVED"
                    and (receiver is None or r["receiver"] == receiver)]
        if len(emissions) != 1:
            return {"emission": "UNKNOWN", "arrival": "UNKNOWN"}
        return {"emission": "EMITTED", "arrival": "HARNESS_OBSERVED" if observed else "UNKNOWN",
                "receivers": [r["receiver"] for r in observed]}
    except (OSError, ValueError, TypeError, KeyError):
        return {"emission": "UNKNOWN", "arrival": "UNKNOWN"}


def main():
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="Read exact spec observation identity; no send or ACK")
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(4097)
        if len(raw) > 4096:
            raise ValueError("identity capped")
        print(json.dumps(show(args.root, json.loads(raw))))
        return 0
    except (ValueError, TypeError, KeyError):
        print(json.dumps({"emission": "UNKNOWN", "arrival": "UNKNOWN"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
