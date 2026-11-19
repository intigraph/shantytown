"""aegis-jve: a quipu busy signal counts from a fresh labelled snapshot; nothing else does."""
import json
import time

import pytest

from shantytown import owner_snapshot
from shantytown.answer import Answer
from shantytown.plate_capacity import CapacityUnknown, PlateFull, ensure_room, size
from shantytown.sd import StoreProof


def row(n, owner='worker', status='open'):
    return {'id': f'aegis-{n}', 'title': f'work {n}', 'status': status, 'assignee': owner}


class Tracker:
    """A Seeds-shaped tracker whose next capacity read is scripted."""

    def __init__(self, graph='https://seeds.local/project/aegis'):
        self.graph = graph
        self.answer = None

    def prove_store(self):
        return StoreProof('fixture', None, 'http://quipu.example', 'aegis', self.graph)

    def capacity_rows(self, owner):
        return self.answer


@pytest.fixture(autouse=True)
def private_cache(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))


def busy():
    return Answer.capped([], how='Seeds capacity owner scope',
                         caveat='HTTP Error 408: Request Timeout')


def age_snapshot(tracker, owner, seconds):
    ident = owner_snapshot.identity(tracker)
    path = owner_snapshot._path(ident, owner)
    data = json.loads(path.read_text())
    data['at'] = time.time() - seconds
    path.write_text(json.dumps(data))


def test_busy_read_counts_from_fresh_snapshot_instead_of_refusing(capsys):
    """FAILING-FIRST: on main any failed read is 'plate size UNKNOWN' and refuses."""
    tracker = Tracker()
    tracker.answer = Answer.complete_read([row(1), row(2)], how='live')
    assert size(tracker, 'worker') == 2
    tracker.answer = busy()
    ensure_room(tracker, 'worker')  # admitted from the 2-row snapshot
    assert 'from snapshot age=' in capsys.readouterr().err


def test_old_snapshot_still_refuses():
    tracker = Tracker()
    tracker.answer = Answer.complete_read([row(1)], how='live')
    size(tracker, 'worker')
    age_snapshot(tracker, 'worker', owner_snapshot.MAX_AGE + 30)
    tracker.answer = busy()
    with pytest.raises(CapacityUnknown, match='plate size UNKNOWN'):
        ensure_room(tracker, 'worker')


def test_non_transient_failure_never_uses_the_snapshot():
    tracker = Tracker()
    tracker.answer = Answer.complete_read([row(1)], how='live')
    size(tracker, 'worker')
    tracker.answer = Answer.capped([], how='owner scope', caveat='truncated')
    with pytest.raises(CapacityUnknown, match='truncated'):
        ensure_room(tracker, 'worker')


def test_snapshot_from_another_store_is_not_used():
    first = Tracker()
    first.answer = Answer.complete_read([row(1)], how='live')
    size(first, 'worker')
    other = Tracker(graph='https://seeds.local/project/other')
    other.answer = busy()
    with pytest.raises(CapacityUnknown):
        ensure_room(other, 'worker')


def test_a_full_snapshot_still_enforces_the_cap():
    tracker = Tracker()
    tracker.answer = Answer.complete_read([row(n) for n in range(10)], how='live')
    size(tracker, 'worker')
    tracker.answer = busy()
    with pytest.raises(PlateFull, match='10/10'):
        ensure_room(tracker, 'worker')


def test_a_successful_read_always_wins_over_the_snapshot():
    tracker = Tracker()
    tracker.answer = Answer.complete_read([row(n) for n in range(10)], how='live')
    size(tracker, 'worker')
    tracker.answer = Answer.complete_read([row(1)], how='live')
    ensure_room(tracker, 'worker')  # live says 1, not the snapshot's 10
    assert size(tracker, 'worker') == 1


def test_tracker_without_store_proof_keeps_refusing():
    class Plain:
        answer = busy()

        def capacity_rows(self, owner):
            return self.answer
    with pytest.raises(CapacityUnknown):
        ensure_room(Plain(), 'worker')


@pytest.mark.parametrize('text,expected', [
    ('HTTP Error 408: Request Timeout', True),
    ('HTTP Error 429: Too Many Requests', True),
    ('HTTP Error 503: Service Unavailable', True),
    ('<urlopen error timed out>', True),
    ('truncated', False),
    ('owner listing completeness unproven for aegis-503', False),
    ('aegis-408 and aegis-429 are open', False),
    ('status 503', True),
    ('code=429', True),
    ('owner has an unsupported or absent status', False),
    ('owner listing completeness unproven', False),
])
def test_only_busy_signals_are_transient(text, expected):
    assert owner_snapshot.transient(text) is expected


def test_snapshot_files_are_private(tmp_path):
    tracker = Tracker()
    tracker.answer = Answer.complete_read([row(1)], how='live')
    size(tracker, 'worker')
    path = owner_snapshot._path(owner_snapshot.identity(tracker), 'worker')
    assert path.stat().st_mode & 0o077 == 0
    assert path.parent.stat().st_mode & 0o077 == 0
