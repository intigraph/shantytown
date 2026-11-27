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
