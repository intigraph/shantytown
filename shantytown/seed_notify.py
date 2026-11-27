"""Tell the administrator about every NEW seed, batched, with its likely duplicates.

Stiwi 2026-11-27, verbatim: "I feel st should notify you when new seeds are
created so you can prioritize and also reject or modify or link to others".
Before this, a new seed reached the administrator only through a hand sweep or a
ranking check, so duplicates, unranked items and missing links piled up (the
backlog stood at 296 against a 200 cap).

The board's creation order is the change feed: each tend pass reads the items
created after the last cursor, so a seed is seen once whoever made it (`st task`,
a bare `sd create`, a scheduled seed). A hook on `st task` alone would miss every
other creator. The sweep then delivers ONE notice per burst:

  pending   new items wait until the burst has been quiet for WINDOW seconds,
            or until the oldest has waited MAX_WAIT, so five creates in a row
            are one notice, not five.
  flushed   one push to the administrator: id, title, priority, labels,
            creator, and the top RELATED_TOP likely duplicates or related open
            items, with the four dispositions spelled out.

Excluded: inbox pointer seeds (`inbox.is_message`, or the `inbox` label) and
ephemeral job reports. They are delivery mechanics, not work to rank.

Related items are scored here, from the listing already in hand, by title and
description word overlap. No second service is asked, so a down search index
cannot hide a duplicate or stall the notice; it is a hint, and the notice says so.

FAIL OPEN, like every tend sweep: an unreadable board is logged and retried. The
cursor advances and the pending batch clears ONLY after the push landed, so an
unreachable administrator pane leaves the batch for the next pass.

The first pass has no cursor. It records the newest creation time and notifies
nothing: announcing the whole existing backlog as "new" would be one useless wall.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

WINDOW = 120            # quiet seconds that close a burst
MAX_WAIT = 600          # a steady trickle still flushes at least this often
RELATED_TOP = 3
RELATED_MIN = 0.2       # Jaccard floor; below it a "match" is shared filler words
LISTED_CAP = 20         # items spelled out in one notice; the rest are counted
SEEN_CAP = 2000
_WORD = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")
_STOP = frozenset(
    "the and for with from that this into when then than not are was were its "
    "has have but can all any each one new st via per use"
    .split())


def _time(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _labels(row: dict) -> list[str]:
    raw = row.get("labels") or []
    if isinstance(raw, str):
        raw = raw.split(",")
    return [str(label).strip() for label in raw if str(label).strip()]


def excluded(row: dict) -> bool:
    """An inbox pointer or an ephemeral job report: mechanics, not work to rank."""
    from .inbox import is_message
    title = (row.get("title") or "").lstrip()
    labels = set(_labels(row))
    if is_message(title) or "inbox" in labels:
        return True
    if title.lower().startswith("[ephemeral"):
        return True
    return any(label.startswith(("ephemeral-report", "job-report")) for label in labels)


def _words(row: dict) -> frozenset[str]:
    text = f"{row.get('title') or ''} {row.get('description') or ''}".lower()
    return frozenset(w for w in _WORD.findall(text) if w not in _STOP)


def related(row: dict, board: list[dict], top: int = RELATED_TOP) -> list[tuple[str, str, float]]:
    """The `top` open items most like `row`: [(id, title, score)], best first."""
    mine = _words(row)
    if not mine:
        return []
    scored = []
    for other in board:
        if other.get("id") == row.get("id") or other.get("status") == "closed":
            continue
        if excluded(other):
            continue
        theirs = _words(other)
        if not theirs:
            continue
        score = len(mine & theirs) / len(mine | theirs)
        if score >= RELATED_MIN:
            scored.append((score, str(other.get("id")), other.get("title") or ""))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [(i, t, round(s, 2)) for s, i, t in scored[:top]]


def _creator(row: dict) -> str:
    for key in ("created_by", "creator", "requester", "owner"):
        if row.get(key):
            return str(row[key])
    return "UNKNOWN"


def render(entries: list[dict], now: datetime) -> str:
    count = len(entries)
    lines = [f"🌱 NEW SEEDS ({count}) — rank, reject (close with reason), modify, or link "
             f"each one this cycle:"]
    for entry in entries[:LISTED_CAP]:
        priority = entry.get("priority")
        lines.append(
            f"• {entry['id']} P{priority if priority is not None else '?'} "
            f"[{', '.join(entry.get('labels') or []) or 'no labels'}] by {entry['creator']}: "
            f"{(entry.get('title') or '')[:100]}")
        for rid, rtitle, score in entry.get("related") or []:
            lines.append(f"    ≈ {rid} ({score}) {rtitle[:80]}")
        if not entry.get("related"):
            lines.append("    ≈ no likely duplicate on the board")
    if count > LISTED_CAP:
        lines.append(f"… and {count - LISTED_CAP} more created in this burst.")
    lines.append("≈ is word overlap with open items: a lead to check, not a verdict. "
                 "Act with `st work item update <id> --rank/--priority`, "
                 "`st work item close <id>`, or a dependency link.")
    return "\n".join(lines)


class NewSeedNotifier:
    def __init__(self, root, reg, panes, *, push=None, rows=None, now=None, log=None):
        self._root = root
        self.path = Path(root) / "notify" / "new-seeds.json"
        self._reg, self._panes = reg, panes
        self._push = push
        self._rows = rows
        self._now = now
        self._log = log or (lambda msg: None)

    def _clock(self) -> datetime:
        return self._now() if self._now else datetime.now(timezone.utc)

    def _load(self) -> dict | None:
        try:
            state = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(state, dict) or not isinstance(state.get("cursor"), str):
            return None
        state.setdefault("pending", [])
        state.setdefault("seen", [])
        return state

    def _save(self, state: dict) -> None:
        from .files import write_json_atomic
        state["seen"] = state["seen"][-SEEN_CAP:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.path, state)

    def _board(self) -> list[dict]:
        if self._rows is not None:
            return self._rows()
        from .br import rows
        from .feed_check import _br_tracker
        tracker = _br_tracker(self._root, self._reg)
        if tracker is None:
            raise RuntimeError("no br-like tracker configured")
        return rows(tracker)

    def sweep(self) -> list[str]:
        """Return the ids carried by a notice that landed on this pass, else []."""
        now = self._clock()
        try:
            board = self._board()
        except Exception as e:
            self._log(f"new-seeds: could not read the board ({e!r}); retry next pass")
            return []
        created = [(t, row) for row in board
                   if isinstance(row, dict) and row.get("id")
                   and (t := _time(row.get("created_at"))) is not None]
        state = self._load()
        if state is None:
            newest = max((t for t, _ in created), default=now)
            # Items AT the cursor are not "after" it but are not new either.
            self._save({"cursor": newest.isoformat(), "pending": [],
                        "seen": [str(row["id"]) for t, row in created if t == newest]})
            self._log(f"new-seeds: baseline at {newest.isoformat()}; existing items not announced")
            return []

        cursor = _time(state["cursor"]) or now
        known = set(state["seen"]) | {p["id"] for p in state["pending"]}
        for at, row in sorted(created, key=lambda c: c[0]):
            if at < cursor or row["id"] in known or excluded(row):
                continue
            known.add(row["id"])
            state["pending"].append({
                "id": str(row["id"]), "at": at.isoformat(),
                "title": row.get("title") or "", "priority": row.get("priority"),
                "labels": _labels(row), "creator": _creator(row)})
        if not state["pending"]:
            self._save(state)
            return []

        times = [_time(p["at"]) or now for p in state["pending"]]
        quiet = (now - max(times)).total_seconds() >= WINDOW
        overdue = (now - min(times)).total_seconds() >= MAX_WAIT
        if not (quiet or overdue):
            self._save(state)       # keep the burst open; nothing announced yet
            return []

        by_id = {str(row.get("id")): row for _, row in created}
        entries = []
        for pending in state["pending"]:
            row = by_id.get(pending["id"], pending)
            entries.append({**pending, "related": related(row, board)})
        from .notify import push_to_admin
        push = self._push or push_to_admin
        if not push(self._reg, self._panes, render(entries, now)):
            self._log(f"new-seeds: notice for {len(entries)} seed(s) did not land; retry next pass")
            self._save(state)
            return []
        ids = [p["id"] for p in state["pending"]]
        state["seen"].extend(ids)
        state["cursor"] = max(times).isoformat()
        state["pending"] = []
        self._save(state)
        return ids
