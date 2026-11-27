"""PR-lifecycle events from chaski's `pr-lifecycle` emitter (aegis-za4f.21).

Before this, every PR step (review a new head, fix REQUEST-CHANGES, merge at
green and approved) waited for the administrator to notice and run
`st agent spawn` by hand. On quipu#1354 that meant a merge job spawned before
CI was green and an approval for a stale head. Chaski now watches PR state and
appends one JSONL line per needed action; `st agent spawn --drain-events
<jsonl>` turns each unseen line into the ordinary spawn.

This module is the pure half: the event contract, the ledger that makes the
drain idempotent on event_id, and which events are stale. The spawn itself is
cli._spawn_drain_events, through the same path a hand-typed spawn takes, so
the ephemeral cap and the governor stay the only brakes. It is deliberately
NOT the signed controller recruit_* path: this is a local consumer of a file
on this host.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import re
from contextlib import contextmanager
from pathlib import Path

JOBS = ("review", "task", "merge")
REASONS = ("new-head-unreviewed", "changes-requested", "green-and-approved", "ci-red")
# Which reasons may recruit which job. A line pairing `merge` with `ci-red` is
# an emitter bug, and acting on it would merge on a red head.
JOB_REASONS = {
    "review": ("new-head-unreviewed",),
    "task": ("changes-requested", "ci-red"),
    "merge": ("green-and-approved",),
}
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SHA = re.compile(r"[0-9a-f]{40}")
_ITEM = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_ID = re.compile(r"[0-9a-f]{64}")

LEDGER = "pr-events.jsonl"


def event_id(repo: str, pr: int, head: str, job: str) -> str:
    """The contract's id: sha256 of `repo|pr|head|job`. One event per tuple ever;
    a new head is a new tuple, so a push re-arms review."""
    return hashlib.sha256(f"{repo}|{pr}|{head}|{job}".encode()).hexdigest()


def parse(line: str) -> dict:
    """One validated event, or ValueError naming what is wrong. Every field is
    checked because each one becomes an argv value for the spawn."""
    try:
        ev = json.loads(line)
    except json.JSONDecodeError as e:
        raise ValueError(f"not JSON ({e.msg})") from None
    if not isinstance(ev, dict):
        raise ValueError("not a JSON object")
    repo, pr, head, job = ev.get("repo"), ev.get("pr"), ev.get("head"), ev.get("job")
    if not isinstance(repo, str) or not _REPO.fullmatch(repo):
        raise ValueError(f"repo {repo!r} is not OWNER/NAME")
    if isinstance(pr, bool) or not isinstance(pr, int) or pr < 1:
        raise ValueError(f"pr {pr!r} is not a positive integer")
    if not isinstance(head, str) or not _SHA.fullmatch(head):
        raise ValueError(f"head {head!r} is not a 40-hex SHA")
    if job not in JOBS:
        raise ValueError(f"job {job!r} is not one of {'|'.join(JOBS)}")
    reason = ev.get("reason")
    if reason not in REASONS:
        raise ValueError(f"reason {reason!r} is not one of {'|'.join(REASONS)}")
    if reason not in JOB_REASONS[job]:
        raise ValueError(f"reason {reason} never recruits a {job} job")
    item = ev.get("item")
    if item is not None and (not isinstance(item, str) or not _ITEM.fullmatch(item)):
        raise ValueError(f"item {item!r} is not a work item id")
    eid = ev.get("event_id")
    if not isinstance(eid, str) or not _ID.fullmatch(eid):
        raise ValueError("event_id is not a sha256 hex digest")
    if eid != event_id(repo, pr, head, job):
        # A mismatched id would let one line defeat idempotency for another.
        raise ValueError("event_id is not sha256(repo|pr|head|job)")
    return {"event_id": eid, "repo": repo, "pr": pr, "head": head, "job": job,
            "item": item, "reason": reason, "observed_at": ev.get("observed_at")}


def read(path: Path) -> tuple[list[dict], list[str]]:
    """(events in file order, problems). A bad line is reported and skipped,
    never fatal: one malformed append must not stop every later event."""
    events, problems = [], []
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(parse(line))
        except ValueError as e:
            problems.append(f"line {n}: {e}")
    return events, problems


def current_heads(events: list[dict]) -> dict[tuple[str, int], str]:
    """The head each PR was last observed at. The file is append-only, so the
    last line for a PR is the newest observation."""
    return {(e["repo"], e["pr"]): e["head"] for e in events}


def ledger_path(root) -> Path:
    from .ephemeral import ledger_dir
    return ledger_dir(root) / LEDGER


def settled(root) -> dict[str, dict]:
    """event_id -> its settling record. Unreadable lines are skipped: at worst an
    event is offered again, and the spawn path refuses a duplicate live job."""
    out: dict[str, dict] = {}
    try:
        text = ledger_path(root).read_text()
    except FileNotFoundError:
        return out
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("event_id"), str):
            out[rec["event_id"]] = rec
    return out


def settle(root, ev: dict, outcome: str, now: float, detail: str = "") -> None:
    """Append-only, one line per settled event: a crash mid-drain loses at most
    the line being written, and the event is offered again next drain."""
    p = ledger_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"event_id": ev["event_id"], "repo": ev["repo"], "pr": ev["pr"],
           "head": ev["head"], "job": ev["job"], "item": ev["item"],
           "outcome": outcome, "at": now}
    if detail:
        rec["detail"] = detail[:300]
    with open(p, "a") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


@contextmanager
def lock(root):
    """One event drain at a time. Separate from the spawn ledger lock, which
    each spawn takes itself: holding that one here would deadlock."""
    from .ephemeral import ledger_dir
    d = ledger_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / ".pr-events.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def argv(ev: dict, track: str = "roadmap") -> list[str]:
    """The spawn this event asks for, exactly the contract's flags."""
    return ["--ephemeral", "--job", ev["job"], "--item", ev["item"],
            "--repo", ev["repo"], "--pr", str(ev["pr"]), "--head", ev["head"],
            "--track", track]
