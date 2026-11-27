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

The cursor is a FLOOR minus LOOKBACK, not a hard edge, and the seen set (not the
cursor) is what dedupes. The first version skipped every row stamped before the
cursor, so a seed whose created_at precedes the last flush but first reaches the
listing after it (clock skew between creating hosts, a slow commit, a store newly
added to tracker.repos, an imported item) was never announced. Only a row stamped
more than LOOKBACK before the cursor is still out of reach.

A notice lists at most LISTED_CAP seeds; the rest stay pending for the next pass,
so every seed is NAMED to the administrator, never just counted.

Burst timing (WINDOW, MAX_WAIT) runs on first_seen: the created_at stamp, clamped
to no later than the pass that first saw the seed. On the raw stamp, a seed
stamped in the future by a skewed host kept a burst "not quiet" and "not
overdue" until its stamp passed, so MAX_WAIT bounded nothing. Clamping (rather
than the bare first-seen time) keeps an ordinary seed flushing on the first pass
after its burst went quiet. For the same reason the cursor never moves past the
sweep's own clock.

State that is unreadable is not the same as state that is missing. Missing means
first run: baseline. Corrupt is moved aside, logged, and recovered with an empty
seen set at a cursor of now, so every seed inside LOOKBACK is announced again: a
duplicate notice is cheaper than a lost seed. (The first version re-announced
only the last day, which lost a pending late-listed seed stamped earlier.)

A stand-in host (owner unreachable) does NOT announce. Its notify state is its
own, so when the owner returned it re-announced every seed the stand-in had sent.
The owner's cursor already covers the outage, so it catches up on return, but
only for seeds stamped within LOOKBACK of that cursor: an owner outage longer
than LOOKBACK drops the seeds stamped before the floor.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

WINDOW = 120            # quiet seconds that close a burst
MAX_WAIT = 600          # a steady trickle still flushes at least this often
RELATED_TOP = 3
RELATED_MIN = 0.2       # Jaccard floor; below it a "match" is shared filler words
LISTED_CAP = 20         # items spelled out in one notice; the rest wait a pass
LOOKBACK = 7 * 86400    # how far before the cursor a late-listed seed still counts
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


def render(entries: list[dict], now: datetime, held: int = 0) -> str:
    count = len(entries)
    lines = [f"🌱 NEW SEEDS ({count}) — rank, reject (close with reason), modify, or link "
             f"each one this cycle:"]
    for entry in entries:
        priority = entry.get("priority")
        lines.append(
            f"• {entry['id']} P{priority if priority is not None else '?'} "
            f"[{', '.join(entry.get('labels') or []) or 'no labels'}] by {entry['creator']}: "
            f"{(entry.get('title') or '')[:100]}")
        for rid, rtitle, score in entry.get("related") or []:
            lines.append(f"    ≈ {rid} ({score}) {rtitle[:80]}")
        if not entry.get("related"):
            lines.append("    ≈ no likely duplicate on the board")
    if held:
        lines.append(f"… {held} more new seed(s) follow in the next notice.")
    lines.append("≈ is word overlap with open items: a lead to check, not a verdict. "
                 "Act with `st work item update <id> --rank/--priority`, "
                 "`st work item close <id>`, or a dependency link.")
    return "\n".join(lines)


class NewSeedNotifier:
    def __init__(self, root, reg, panes, *, push=None, rows=None, now=None, log=None,
                 stand_in=False):
        self._root = root
        self.path = Path(root) / "notify" / "new-seeds.json"
        self._reg, self._panes = reg, panes
        self._push = push
        self._rows = rows
        self._now = now
        self._log = log or (lambda msg: None)
        self._stand_in = stand_in

    def _clock(self) -> datetime:
        return self._now() if self._now else datetime.now(timezone.utc)

    def _load(self) -> dict | None:
        """The saved state; None when there is none yet (first run).

        Raises ValueError when a file exists but cannot be used, so the caller can
        say so instead of silently re-baselining over a pending batch."""
        try:
            text = self.path.read_text()
        except FileNotFoundError:
            return None
        except OSError as e:
            raise ValueError(f"unreadable: {e!r}") from e
        state = json.loads(text)        # a JSONDecodeError is a ValueError
        if not isinstance(state, dict) or not isinstance(state.get("cursor"), str) \
                or _time(state["cursor"]) is None:
            raise ValueError("no usable cursor")
        pending = state.get("pending") or []
        seen = state.get("seen") or {}
        if isinstance(seen, list):      # the first format kept bare ids
            seen = {str(i): state["cursor"] for i in seen}
        if not isinstance(pending, list) or not isinstance(seen, dict):
            raise ValueError("pending/seen malformed")
        state["pending"], state["seen"] = pending, seen
        return state

    def _save(self, state: dict) -> None:
        from .files import write_json_atomic
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.path, state)

    @staticmethod
    def _baseline(created, at: datetime) -> dict:
        """State whose cursor is `at`: rows up to it (back to the floor) are known."""
        floor = at - timedelta(seconds=LOOKBACK)
        return {"cursor": at.isoformat(), "pending": [],
                "seen": {str(row["id"]): t.isoformat() for t, row in created
                         if floor <= t <= at}}

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
        if self._stand_in:
            self._log("new-seeds: standing in for an unreachable owner; not announcing, "
                      "the owner's cursor catches up when it returns")
            return []
        now = self._clock()
        try:
            board = self._board()
        except Exception as e:
            self._log(f"new-seeds: could not read the board ({e!r}); retry next pass")
            return []
        created = [(t, row) for row in board
                   if isinstance(row, dict) and row.get("id")
                   and (t := _time(row.get("created_at"))) is not None]
        try:
            state = self._load()
        except ValueError as e:
            aside = self.path.with_name(self.path.name + ".corrupt")
            try:
                self.path.replace(aside)
            except OSError:
                pass
            floor = now - timedelta(seconds=LOOKBACK)
            self._log(f"new-seeds: state file {self.path} is UNUSABLE ({e}); kept as {aside}; "
                      f"re-announcing seeds since {floor.isoformat()} rather than lose any")
            state = {"cursor": now.isoformat(), "pending": [], "seen": {}}
        if state is None:
            newest = max((t for t, _ in created), default=now)
            self._save(self._baseline(created, newest))
            self._log(f"new-seeds: baseline at {newest.isoformat()}; existing items not announced")
            return []
        cursor = _time(state["cursor"]) or now
        floor = cursor - timedelta(seconds=LOOKBACK)
        known = set(state["seen"]) | {p["id"] for p in state["pending"]}
        for at, row in sorted(created, key=lambda c: c[0]):
            if at < floor or str(row["id"]) in known or excluded(row):
                continue
            known.add(str(row["id"]))
            state["pending"].append({
                "id": str(row["id"]), "at": at.isoformat(), "first_seen": min(at, now).isoformat(),
                "title": row.get("title") or "", "priority": row.get("priority"),
                "labels": _labels(row), "creator": _creator(row)})
        if not state["pending"]:
            self._save(state)
            return []

        # Pending written before first_seen existed falls back to its stamp.
        times = [min(_time(p.get("first_seen")) or _time(p["at"]) or now, now)
                 for p in state["pending"]]
        quiet = (now - max(times)).total_seconds() >= WINDOW
        overdue = (now - min(times)).total_seconds() >= MAX_WAIT
        if not (quiet or overdue):
            self._save(state)       # keep the burst open; nothing announced yet
            return []

        by_id = {str(row.get("id")): row for _, row in created}
        state["pending"].sort(key=lambda p: _time(p["at"]) or now)
        batch, held = state["pending"][:LISTED_CAP], state["pending"][LISTED_CAP:]
        entries = []
        for pending in batch:
            row = by_id.get(pending["id"], pending)
            entries.append({**pending, "related": related(row, board)})
        from .notify import push_to_admin
        push = self._push or push_to_admin
        if not push(self._reg, self._panes, render(entries, now, held=len(held))):
            self._log(f"new-seeds: notice for {len(entries)} seed(s) did not land; retry next pass")
            self._save(state)
            return []
        ids = [p["id"] for p in batch]
        for p in batch:
            state["seen"][p["id"]] = p["at"]
        flushed = min(max(_time(p["at"]) or now for p in batch), now)
        cursor = max(cursor, flushed)
        state["cursor"] = cursor.isoformat()
        state["pending"] = held
        # A seen id older than the floor can never be a candidate again.
        floor = cursor - timedelta(seconds=LOOKBACK)
        state["seen"] = {i: t for i, t in state["seen"].items()
                         if (_time(t) or cursor) >= floor}
        self._save(state)
        return ids
