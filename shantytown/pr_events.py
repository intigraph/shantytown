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
# Outcomes that end an event. "refused" (dates the first refusal),
# "spawning" (intent, written before the spawn), "launch-failure" (one spawn
# that made a job which then failed to launch) and "malformed" (a bad line
# already reported, keyed by line_id) are also written; none settles an event.
SETTLING = ("admitted", "superseded", "expired", "launch-failed")
# Failed launches an event gets before it is settled "launch-failed" and raised
# to the administrator. Before this a launch failure only left the event
# pending, so every drain made one more job: bobbin#259's merge event
# (aegis-qi22) launched 8 merge jobs about 150 s apart, each dying on the same
# bug, for a PR that had already merged. A governor or pool refusal makes no
# job and is not counted; PENDING_TTL_S bounds those.
MAX_LAUNCH_FAILURES = 3
# How long a pending event is offered again before it expires. Without a bound
# a permanent refusal (a merge pin mismatch, a PR closed with no newer head)
# re-spawned on every drain and held exit 2 forever (review of #776), so a
# drain could never go clean. A day covers a governor hold or a full pool; an
# expiry is written to the ledger and printed, never silent.
PENDING_TTL_S = 24 * 3600


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


def line_id(line: str) -> str:
    """A malformed line's ledger key: sha256 of its text, since it has no
    trustworthy event_id of its own."""
    return hashlib.sha256(line.encode()).hexdigest()


def read(path: Path) -> tuple[list[dict], list[tuple[str, str]]]:
    """(events in file order, problems as (line_id, message)). A bad line is
    reported and skipped, never fatal: one malformed append must not stop
    every later event."""
    events, problems = [], []
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(parse(line))
        except ValueError as e:
            problems.append((line_id(line), f"line {n}: {e}"))
    return events, problems


def current_heads(events: list[dict]) -> dict[tuple[str, int], str]:
    """The head each PR was last observed at. The file is append-only, so the
    last line for a PR is the newest observation. That is an emitter contract
    requirement: lines are appended in observation order. A line appended out
    of order would supersede the newer head it came after."""
    return {(e["repo"], e["pr"]): e["head"] for e in events}


def ledger_path(root) -> Path:
    from .ephemeral import ledger_dir
    return ledger_dir(root) / LEDGER


def _ledger(root) -> list[dict]:
    try:
        text = ledger_path(root).read_text()
    except FileNotFoundError:
        return []
    out = []
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("event_id"), str):
            out.append(rec)
    return out


def settled(root) -> dict[str, dict]:
    """event_id -> its settling record. Unreadable lines are skipped: at worst an
    event is offered again, and in_flight() then finds the job it launched."""
    return {r["event_id"]: r for r in _ledger(root) if r.get("outcome") in SETTLING}


def first_refused(root) -> dict[str, float]:
    """event_id -> when it was first left pending, the clock PENDING_TTL_S runs on."""
    out: dict[str, float] = {}
    for r in _ledger(root):
        if r.get("outcome") == "refused" and isinstance(r.get("at"), (int, float)):
            out.setdefault(r["event_id"], r["at"])
    return out


def malformed_seen(root) -> set[str]:
    """line_ids of malformed lines already reported. The file is append-only,
    so a bad line stays in it forever; without this record it held exit 2 on
    every later drain, the never-goes-clean problem PENDING_TTL_S fixes for
    refusals (review of #776). The first sighting is still exit 2."""
    return {r["event_id"] for r in _ledger(root) if r.get("outcome") == "malformed"}


def note_malformed(root, lid: str, problem: str, now: float) -> None:
    p = ledger_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"event_id": lid, "outcome": "malformed", "at": now, "detail": problem[:300]}
    with open(p, "a") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def launch_failures(root) -> dict[str, int]:
    """event_id -> how many of its spawns made a job that failed to launch."""
    out: dict[str, int] = {}
    for r in _ledger(root):
        if r.get("outcome") == "launch-failure":
            out[r["event_id"]] = out.get(r["event_id"], 0) + 1
    return out


def new_jobs(ev: dict, before: set[str], after: list[dict]) -> list[str]:
    """Job records for this event's step that one spawn created: in `after`
    (eph.records) but not in `before` (their names before the spawn). A spawn
    that returned non-OK and left one of these behind made a job that failed
    to launch; one that left none was refused before any job existed."""
    return [r["name"] for r in after
            if r.get("name") not in before
            and (r.get("job"), r.get("repo"), r.get("pr")) == (ev["job"], ev["repo"], ev["pr"])]


def pr_state(ev: dict, info: dict) -> str | None:
    """Why this event's step no longer applies to the PR as the forge reports
    it now (`gh api repos/R/pulls/N`), or None while it still does. The file is
    append-only and the emitter can lag, so its last line is not the PR's
    state: bobbin#259 merged at 01:56Z and its merge event kept spawning."""
    if info.get("merged") or info.get("merged_at"):
        return "pr-merged"
    if info.get("state") == "closed":
        return "pr-closed"
    sha = (info.get("head") or {}).get("sha")
    if isinstance(sha, str) and sha and sha != ev["head"]:
        return f"head moved to {sha[:12]}"
    return None


def attempted(root) -> dict[str, float]:
    """event_id -> when its spawn was first started: the intent line written
    just before it. in_flight() needs the time, not just the fact."""
    out: dict[str, float] = {}
    for r in _ledger(root):
        if r.get("outcome") == "spawning":
            at = r.get("at")
            out.setdefault(r["event_id"], at if isinstance(at, (int, float)) else 0.0)
    return out


def in_flight(ev: dict, live: list[dict], tickets: list[dict], since: float) -> str | None:
    """The live job or queued ticket already doing this event's step, or None.
    A drain that crashed after the spawn succeeded but before settle() offers
    the event again, and the spawn path itself does not refuse a duplicate
    (review of #776), so this is the check that stops a second launch.

    Only asked for an event that attempted() names, since an event never
    spawned cannot be running; `since` is that attempt's intent time. A merge
    record keeps its head and must match it exactly. Legacy or offline review
    and task records may have no proved head, so a head-less
    record matches on job, repo and PR only if it was spawned or queued at or
    after the intent. Before, any head-less record matched: a hand-spawned
    task on an older head of the same PR settled a new head's refused event
    as admitted, and the new head's fix never ran (review of #776)."""
    for r in [*live, *tickets]:
        if r.get("state") == "launching":
            continue
        if (r.get("job"), r.get("repo"), r.get("pr")) != (ev["job"], ev["repo"], ev["pr"]):
            continue
        if r.get("head") is not None:
            if r["head"] != ev["head"]:
                continue
        else:
            born = r.get("spawned_at", r.get("enqueued_at"))
            if not isinstance(born, (int, float)) or born < since:
                continue
        return r.get("name") or r.get("id") or "?"
    return None


def occupied(ev: dict, live: list[dict], tickets: list[dict]) -> tuple[str, bool] | None:
    """(name, exact) of ANY live job or queued ticket already doing this
    event's job on this PR, whoever launched it, or None.

    in_flight() only answers for the drain's own earlier attempts, so a job the
    administrator spawned by hand for the same step was invisible: on 11-27
    (aegis-8et) 9 of 10 concurrent duplicate jobs were a hand spawn plus a drain
    spawn of the same job/repo/PR 29-91 s apart, three were stopped by hand,
    and two pairs returned opposite verdicts on one head.

    exact=True: the record keeps this very head, so it IS this event's step and
    the event may settle as admitted once the job is live (or queued).
    exact=False: a head-less record, a job still launching, or a task on
    another head of this branch. It may be on an older head, so it must NOT
    settle the event (the
    stale-head failure of the #776 review); the caller only holds the event
    back until that job ends. Two concurrent task jobs on one PR branch would
    also race their pushes. A review or merge on a different explicit head is
    another step and does not count."""
    loose = None
    for r in [*live, *tickets]:
        if (r.get("job"), r.get("repo"), r.get("pr")) != (ev["job"], ev["repo"], ev["pr"]):
            continue
        name = r.get("name") or r.get("id") or "?"
        if r.get("head") is not None:
            if r["head"] == ev["head"]:
                if r.get("state") == "launching":
                    loose = loose or name
                    continue
                return name, True
            if ev["job"] == "task":
                loose = loose or name
            continue
        loose = loose or name
    return (loose, False) if loose else None


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
