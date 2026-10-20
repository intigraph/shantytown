"""Reviewed natural-event bindings. No item-supplied commands, paths or queries.

The initial producer contract is deliberately disabled pending its owner's
acceptance. Enabling a binding is a reviewed source change, not a CLI option.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_BYTES = 64 * 1024
MAX_EVENTS = 1000
FRESH = timedelta(minutes=30)
HORIZON = timedelta(days=14)


@dataclass(frozen=True)
class Binding:
    item: str
    producer: str
    host: str
    unit: str
    generation: str
    window: str
    not_before: datetime
    accepted: bool = False


# Malcolm owns the producer contract. Identity placeholders cannot be activated
# by evidence; source review must replace them and explicitly accept the binding.
REGISTRY = {"protected-recycle-v1": Binding(
    "aegis-67p0lj", "", "", "", "", "",
    datetime(2026, 10, 16, 18, 33, tzinfo=timezone.utc))}


@dataclass(frozen=True)
class Verdict:
    state: str
    reason: str
    digest: str = ""
    events: tuple[str, ...] = ()


def binding_for(identifier: str, item: str) -> Binding:
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", identifier):
        raise ValueError("invalid event binding ID")
    binding = REGISTRY.get(identifier)
    if binding is None or binding.item != item:
        raise ValueError("event binding is not registered for this item")
    if not binding.accepted or not all((binding.producer, binding.host,
            binding.unit, binding.generation, binding.window)):
        raise ValueError("event producer contract is disabled pending acceptance")
    return binding


def _stamp(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("event timestamp must be explicit UTC")
    value = datetime.fromisoformat(value[:-1] + "+00:00")
    if value.tzinfo is None:
        raise ValueError("event timestamp has no timezone")
    return value


def _integer(value):
    if type(value) is not int or value < 0:
        raise ValueError("invalid event sequence")
    return value


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate evidence field")
        out[key] = value
    return out


def _read(identifier):
    # The marker never selects a path. Reject links at every component, and
    # refuse FIFOs/devices and writable-by-others evidence before reading it.
    root = Path.home() / ".local/state/shantytown/resume-events"
    path = root / (identifier + ".json")
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        info = os.fstat(directory)
        if info.st_mode & 0o022 or info.st_uid not in (0, os.geteuid()):
            raise ValueError("untrusted event evidence directory")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
    finally:
        os.close(directory)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_mode & 0o022
                or before.st_uid not in (0, os.geteuid())
                or before.st_size > MAX_BYTES):
            raise ValueError("untrusted or oversized event evidence")
        raw = os.read(fd, MAX_BYTES + 1)
        after = os.fstat(fd)
        if (len(raw) > MAX_BYTES or len(raw) != before.st_size
                or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("event evidence changed during read")
        return raw
    finally:
        os.close(fd)


def decide(binding: Binding, evidence: dict, now: datetime) -> Verdict:
    """A complete, fresh interval proves an ordered natural pair or its absence."""
    try:
        if evidence["schema"] != 1 or type(evidence["schema"]) is not int:
            raise ValueError("unsupported event evidence schema")
        for key in ("item", "producer", "host", "unit", "generation", "window"):
            if evidence[key] != getattr(binding, key):
                raise ValueError("event identity/scope mismatch")
        start, end, observed = (_stamp(evidence[k]) for k in
                                ("capture_start", "capture_end", "observed_at"))
        ws, we = (_stamp(evidence[k]) for k in ("window_start", "window_end"))
        if (now.tzinfo is None or not binding.not_before <= start <= ws < we <= end <= observed <= now
                or now - observed > FRESH or now - binding.not_before > HORIZON
                or end - start > HORIZON):
            raise ValueError("stale, expired or invalid event interval")
        if evidence["complete"] is not True or evidence["gaps"] != []:
            raise ValueError("event coverage is incomplete")
        rows = evidence["events"]
        if not isinstance(rows, list) or len(rows) > MAX_EVENTS:
            raise ValueError("event count limit exceeded or invalid")
        lo, hi = (_integer(evidence[k]) for k in ("sequence_start", "sequence_end"))
        if hi < lo - 1 or hi - lo + 1 != len(rows):
            raise ValueError("event sequence coverage mismatch")
        seen, previous, soft = set(), start, None
        pair = None
        for index, event in enumerate(rows):
            if event["generation"] != binding.generation:
                raise ValueError("event crossed a producer/boot generation")
            if _integer(event["sequence"]) != lo + index:
                raise ValueError("event sequence gap or reorder")
            identifier, at, kind = event["id"], _stamp(event["at"]), event["kind"]
            if not isinstance(identifier, str) or not identifier or identifier in seen:
                raise ValueError("invalid or duplicate event ID")
            seen.add(identifier)
            if not previous <= at <= end:
                raise ValueError("event clock discontinuity")
            previous = at
            if kind in ("manual-restart", "hard-override"):
                soft = None
            elif kind == "soft-defer":
                if type(event["natural"]) is not bool:
                    raise ValueError("invalid event origin")
                soft = identifier if event["natural"] and ws <= at < we else None
            elif kind == "recycle":
                if type(event["natural"]) is not bool or type(event["success"]) is not bool:
                    raise ValueError("invalid recycle result/origin")
                if soft and at >= we and event["natural"] and event["success"]:
                    pair = (soft, identifier)
            else:
                raise ValueError("unknown event type")
        if pair:
            return Verdict("MET", "qualifying natural ordered pair", events=pair)
        return Verdict("NOT_MET", "complete interval has no qualifying natural pair")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return Verdict("UNKNOWN", str(exc))


def evaluate(identifier: str, item: str, now: datetime) -> Verdict:
    try:
        binding = binding_for(identifier, item)
        raw = _read(identifier)
        evidence = json.loads(raw, object_pairs_hook=_unique,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        result = decide(binding, evidence, now)
        return Verdict(result.state, result.reason, hashlib.sha256(raw).hexdigest(), result.events)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        return Verdict("UNKNOWN", str(exc))
