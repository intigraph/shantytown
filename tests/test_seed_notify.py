"""Every new non-pointer seed reaches the administrator in ONE batched notice.

Stiwi 2026-11-27: "st should notify you when new seeds are created so you can
prioritize and also reject or modify or link to others"."""
from datetime import datetime, timedelta, timezone

from shantytown import seed_notify
from shantytown.seed_notify import NewSeedNotifier, excluded, related

T0 = datetime(2026, 11, 27, 4, 0, tzinfo=timezone.utc)


def _iso(t):
    return t.isoformat().replace("+00:00", "Z")


def _row(bid, title, at, **kw):
    return {"id": bid, "title": title, "created_at": _iso(at), "status": "open",
            "priority": kw.pop("priority", 2), "labels": kw.pop("labels", []), **kw}


class _World:
    def __init__(self, board, push_ok=True):
        self.board, self.msgs, self.push_ok = board, [], push_ok
        self.now = T0

    def notifier(self, tmp_path):
        def push(reg, panes, msg):
            self.msgs.append(msg)
            return "sattler" if self.push_ok else None
        return NewSeedNotifier(tmp_path, None, None, push=push,
                               rows=lambda: list(self.board), now=lambda: self.now)

    def tick(self, tmp_path, seconds):
        self.now += timedelta(seconds=seconds)
        return self.notifier(tmp_path).sweep()


EXISTING = [
    _row("aegis-1", "tend: notify administrator about stalled crons", T0 - timedelta(days=2)),
    _row("aegis-2", "cost: daily spend report for the fleet", T0 - timedelta(days=1)),
]


def _baselined(tmp_path, board=None):
    world = _World(list(board or EXISTING))
    assert world.notifier(tmp_path).sweep() == []          # baseline pass
    return world


def test_first_pass_baselines_and_never_announces_the_backlog(tmp_path):
    world = _baselined(tmp_path)
    assert world.msgs == []
    assert world.tick(tmp_path, 3600) == []
    assert world.msgs == []


def test_one_seed_gives_exactly_one_notice_carrying_its_related_items(tmp_path):
    world = _baselined(tmp_path)
    world.board.append(_row("aegis-9", "tend: notify the administrator about stalled crons quickly",
                            world.now + timedelta(seconds=5), labels=["lane:ops"],
                            created_by="hammond"))
    assert world.tick(tmp_path, 10) == []                   # burst still open
    assert world.msgs == []
    assert world.tick(tmp_path, seed_notify.WINDOW) == ["aegis-9"]
    assert len(world.msgs) == 1
    msg = world.msgs[0]
    assert "aegis-9 P2 [lane:ops] by hammond" in msg
    assert "≈ aegis-1" in msg and "aegis-2" not in msg
    # Announced once: later passes are silent.
    assert world.tick(tmp_path, 3600) == []
    assert len(world.msgs) == 1


def test_a_burst_of_five_is_one_notice(tmp_path):
    world = _baselined(tmp_path)
    for n in range(5):
        world.board.append(_row(f"aegis-b{n}", f"burst item number {n}",
                                world.now + timedelta(seconds=1)))
        assert world.tick(tmp_path, 10) == []
    assert world.tick(tmp_path, seed_notify.WINDOW) == [f"aegis-b{n}" for n in range(5)]
    assert len(world.msgs) == 1
    assert "NEW SEEDS (5)" in world.msgs[0]


def test_an_inbox_pointer_gives_no_notice(tmp_path):
    world = _baselined(tmp_path)
    world.board.append(_row("aegis-m", "inbox: sattler -> hammond", world.now + timedelta(seconds=1),
                            labels=["inbox"]))
    world.board.append(_row("aegis-r", "[ephemeral task] eph-task-1 report",
                            world.now + timedelta(seconds=2)))
    assert world.tick(tmp_path, 10 * seed_notify.WINDOW) == []
    assert world.msgs == []


def test_a_steady_trickle_still_flushes_by_max_wait(tmp_path):
    world = _baselined(tmp_path)
    flushed = []
    for n in range(seed_notify.MAX_WAIT // 60 + 2):
        world.board.append(_row(f"aegis-t{n}", f"trickle {n}", world.now + timedelta(seconds=1)))
        flushed += world.tick(tmp_path, 60)
    assert flushed and len(world.msgs) == 1


def test_an_undelivered_notice_is_kept_and_retried(tmp_path):
    world = _baselined(tmp_path)
    world.push_ok = False
    world.board.append(_row("aegis-u", "undelivered seed", world.now + timedelta(seconds=1)))
    assert world.tick(tmp_path, seed_notify.WINDOW + 5) == []
    assert len(world.msgs) == 1                            # tried, did not land
    world.push_ok = True
    assert world.tick(tmp_path, 60) == ["aegis-u"]
    assert len(world.msgs) == 2


def test_an_unreadable_board_announces_nothing_and_keeps_state(tmp_path):
    world = _baselined(tmp_path)
    world.board.append(_row("aegis-x", "after outage", world.now + timedelta(seconds=1)))

    def broken():
        raise RuntimeError("sd down")
    notifier = NewSeedNotifier(tmp_path, None, None, push=lambda *a: "sattler",
                               rows=broken, now=lambda: world.now + timedelta(hours=1))
    assert notifier.sweep() == []
    world.now += timedelta(hours=1)
    assert world.tick(tmp_path, seed_notify.WINDOW) == ["aegis-x"]


def test_excluded_says_no_to_real_work():
    assert not excluded({"title": "fix the thing", "labels": ["lane:product"]})
    assert excluded({"title": "inbox: a -> b", "labels": []})
    assert excluded({"title": "x", "labels": "inbox"})


def test_related_ignores_closed_and_unrelated_items():
    row = {"id": "n", "title": "seeds notify administrator duplicates"}
    board = [{"id": "c", "status": "closed", "title": "seeds notify administrator duplicates"},
             {"id": "u", "status": "open", "title": "gpu fan curve"},
             {"id": "o", "status": "open", "title": "notify administrator about seeds"}]
    assert [r[0] for r in related(row, board)] == ["o"]


def test_a_seed_stamped_before_the_cursor_but_listed_after_a_flush_is_announced(tmp_path):
    # Review of the first version: cursor = newest flushed created_at, and any row
    # stamped before it was skipped, so a late-listed seed (clock skew, slow commit,
    # a store added to tracker.repos) was never announced.
    world = _baselined(tmp_path)
    world.board.append(_row("aegis-new", "fresh seed", world.now + timedelta(seconds=30)))
    assert world.tick(tmp_path, 30 + seed_notify.WINDOW) == ["aegis-new"]
    world.board.append(_row("aegis-late", "skewed host seed", world.now - timedelta(minutes=10)))
    assert world.tick(tmp_path, seed_notify.WINDOW) == ["aegis-late"]
    assert len(world.msgs) == 2 and "• aegis-new" not in world.msgs[1]
    assert world.tick(tmp_path, 3600) == []                # still announced once each


def test_a_row_older_than_the_lookback_stays_out(tmp_path):
    world = _baselined(tmp_path)
    cursor = T0 - timedelta(days=1)                          # newest EXISTING row
    world.board.append(_row("aegis-ancient", "imported long ago",
                            cursor - timedelta(seconds=seed_notify.LOOKBACK + 3600)))
    assert world.tick(tmp_path, 10 * seed_notify.WINDOW) == []


def test_creator_comes_from_the_real_sd_list_field(tmp_path):
    # Shape captured from `sd list --json` on 2026-11-27: the creator is created_by.
    world = _baselined(tmp_path)
    world.board.append({
        "acceptance_criteria": None, "assignee": None, "close_reason": None,
        "closed_at": None, "created_at": _iso(world.now + timedelta(seconds=1)),
        "created_by": "franklin", "defer_until": None, "dependency_count": 0,
        "dependent_count": 0, "description": "", "id": "aegis-g68w.29",
        "issue_type": "task", "labels": [], "priority": 2, "status": "open",
        "title": "captured row", "updated_at": _iso(world.now)})
    assert world.tick(tmp_path, seed_notify.WINDOW + 5) == ["aegis-g68w.29"]
    assert "by franklin" in world.msgs[0] and "UNKNOWN" not in world.msgs[0]


def _corrupt_then_recover(world, tmp_path):
    path = tmp_path / "notify" / "new-seeds.json"
    path.write_text("{not json")
    logs = []
    notifier = NewSeedNotifier(tmp_path, None, None, push=lambda r, p, m: world.msgs.append(m) or "s",
                               rows=lambda: list(world.board), now=lambda: world.now,
                               log=logs.append)
    flushed = notifier.sweep()
    assert any("UNUSABLE" in line for line in logs)
    assert (tmp_path / "notify" / "new-seeds.json.corrupt").read_text() == "{not json"
    return flushed + world.tick(tmp_path, seed_notify.WINDOW)


def test_corrupt_state_is_kept_logged_and_recovered_without_losing_the_batch(tmp_path):
    world = _baselined(tmp_path)
    world.board.append(_row("aegis-p", "pending when the file broke",
                            world.now + timedelta(seconds=1)))
    assert world.tick(tmp_path, 10) == []                   # pending, not yet flushed
    assert "aegis-p" in _corrupt_then_recover(world, tmp_path)   # a silent re-baseline drops it


def test_corrupt_state_recovers_a_pending_late_listed_seed_older_than_a_day(tmp_path):
    # Review of #757: recovery re-announced only the last 24h, so a pending
    # late-listed seed stamped earlier (but inside LOOKBACK) was lost.
    world = _baselined(tmp_path)
    world.board.append(_row("aegis-old", "late-listed, stamped three days back",
                            world.now - timedelta(days=3)))
    world.push_ok = False                                   # its notice does not land
    assert world.tick(tmp_path, 10) == []                   # so it stays pending
    world.push_ok = True
    assert "aegis-old" in _corrupt_then_recover(world, tmp_path)


def test_a_future_stamped_seed_still_flushes_by_max_wait(tmp_path):
    # Review of #757: burst timing on created_at let a seed stamped an hour ahead
    # keep the burst neither quiet nor overdue, so MAX_WAIT bounded nothing.
    world = _baselined(tmp_path)
    world.board.append(_row("aegis-f", "skewed clock, stamped ahead",
                            world.now + timedelta(hours=1)))
    assert world.tick(tmp_path, 1) == []                    # first seen now
    assert world.tick(tmp_path, seed_notify.WINDOW) == ["aegis-f"]


def test_a_missing_state_file_still_baselines_quietly(tmp_path):
    logs = []
    notifier = NewSeedNotifier(tmp_path, None, None, push=lambda *a: "s",
                               rows=lambda: list(EXISTING), now=lambda: T0, log=logs.append)
    assert notifier.sweep() == []
    assert not any("UNUSABLE" in line for line in logs)


def test_a_stand_in_host_does_not_announce_and_the_owner_catches_up(tmp_path):
    world = _baselined(tmp_path)
    standin_root = tmp_path / "standin"
    # Baseline the stand-in's own state BEFORE the seed exists (review of #757:
    # a fresh root only baselined, so the test passed with the guard deleted).
    _baselined(standin_root)

    def stand_in(at):
        return NewSeedNotifier(standin_root, None, None,
                               push=lambda *a: world.msgs.append(a) or "s",
                               rows=lambda: list(world.board), now=lambda: at, stand_in=True)

    world.board.append(_row("aegis-s", "made while the owner was down",
                            world.now + timedelta(seconds=1)))
    for minutes in (1, 30, 60):
        assert stand_in(world.now + timedelta(minutes=minutes)).sweep() == []
    assert world.msgs == []
    assert world.tick(tmp_path, 3600) == ["aegis-s"]       # owner, back, announces it once


def test_a_burst_over_the_cap_names_every_seed_across_notices(tmp_path):
    world = _baselined(tmp_path)
    n = seed_notify.LISTED_CAP + 3
    for i in range(n):
        world.board.append(_row(f"aegis-c{i:02d}", f"cap item {i}", world.now + timedelta(seconds=1)))
    first = world.tick(tmp_path, seed_notify.WINDOW + 5)
    assert len(first) == seed_notify.LISTED_CAP
    assert "3 more new seed(s) follow" in world.msgs[0]
    second = world.tick(tmp_path, seed_notify.MAX_WAIT)
    assert sorted(first + second) == [f"aegis-c{i:02d}" for i in range(n)]
    for i in range(n):
        assert sum(f"• aegis-c{i:02d} " in m for m in world.msgs) == 1
