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
# "spawning" (intent, written before the spawn) and "malformed" (a bad line
# already reported, keyed by line_id) are also written; none settles an event.
SETTLING = ("admitted", "superseded", "expired", "stale", "capped")
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


def stale(ev: dict, pr: dict) -> str:
    """Why the PR as the forge reads it NOW (GET /repos/R/pulls/N) makes this
    event stale, or "". The emitter only emits OPEN PRs, but the file keeps
    every line, so a drain that was off for hours replayed events for PRs
    merged since and spawned review and merge jobs for them (aegis-fl6:
    quipu#1350, camayoc#291, seeds#344). Merged is checked apart from state
    because a merged PR also reads closed, and the ledger should say which."""
    if pr.get("merged") or pr.get("merged_at"):
        return "merged"
    if pr.get("state") != "open":
        return f"closed (state {pr.get('state')!r})"
    sha = (pr.get("head") or {}).get("sha")
    if sha != ev["head"]:
        return f"head moved to {str(sha)[:12]}"
    return ""


# Automated review/fix rounds per PR before a lead must rule (aegis-fl6 added
# scope). Without a cap a reviewer and a fixer that never converge loop on one
# PR, each round a fresh pair of Claude jobs. Merge events are never capped.
REVIEW_CAP = 3
CAPPED_JOBS = ("review", "task")
# A review whose body carries one of these, submitted once the cap is
# reached, is the lead ruling that resumes the loop.
RULING_MARKS = ("pr-risk/accepted", "lead ruling")


def review_cap(reviews: list, cap: int = REVIEW_CAP) -> tuple[int, str]:
    """(REQUEST-CHANGES verdicts counted, key of the round that hit the cap).
    Every head counts: a fixer pushing a new head is exactly the loop being
    capped. A ruling review after the cap starts the count again, so a lead
    can buy three more rounds. The key is the capping review's id, "" while
    under the cap; the notice is posted once per key, not once per tick."""
    count, key = 0, ""
    for r in reviews if isinstance(reviews, list) else []:
        if not isinstance(r, dict):
            continue
        body = str(r.get("body") or "").lower()
        if count >= cap and any(m in body for m in RULING_MARKS):
            count, key = 0, ""
            continue
        if r.get("state") == "CHANGES_REQUESTED":
            count += 1
            if count == cap:
                key = str(r.get("id") or r.get("node_id") or f"round-{cap}")
    return count, key


def cap_notices(root) -> set[tuple[str, int, str]]:
    """(repo, pr, key) of each lead-ruling notice already posted."""
    return {(r.get("repo"), r.get("pr"), r.get("notice")) for r in _ledger(root)
            if r.get("outcome") == "capped" and r.get("notice")}


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
    record keeps its head and must match it exactly. Review and task records
    keep no head (cli builds their Request with head=None), so a head-less
    record matches on job, repo and PR only if it was spawned or queued at or
    after the intent. Before, any head-less record matched: a hand-spawned
    task on an older head of the same PR settled a new head's refused event
    as admitted, and the new head's fix never ran (review of #776)."""
    for r in [*live, *tickets]:
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


def settle(root, ev: dict, outcome: str, now: float, detail: str = "",
           notice: str = "") -> None:
    """Append-only, one line per settled event: a crash mid-drain loses at most
    the line being written, and the event is offered again next drain."""
    p = ledger_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"event_id": ev["event_id"], "repo": ev["repo"], "pr": ev["pr"],
           "head": ev["head"], "job": ev["job"], "item": ev["item"],
           "outcome": outcome, "at": now}
    if detail:
        rec["detail"] = detail[:300]
    if notice:
        rec["notice"] = notice
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
