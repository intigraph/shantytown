"""aegis-jve: every admission read leaves exactly one durable, countable outcome."""
import json

import pytest

from shantytown import plate_outcomes
from shantytown.answer import Answer
from shantytown.plate_capacity import CapacityUnknown, ensure_room, size

from tests.test_owner_snapshot import Tracker, age_snapshot, busy, row  # noqa: F401
from tests.test_owner_snapshot import private_cache  # noqa: F401 - autouse cache isolation


def outcomes():
    return [json.loads(line)['outcome'] for line in plate_outcomes.path().read_text().splitlines()]


def test_live_admission_records_live():
    tracker = Tracker()
    tracker.answer = Answer.complete_read([row(1)], how='live')
    ensure_room(tracker, 'worker')
    assert outcomes() == ['live']


def test_busy_with_fresh_snapshot_records_snapshot_not_a_refusal():
    tracker = Tracker()
    tracker.answer = Answer.complete_read([row(1)], how='live')
    size(tracker, 'worker')  # a non-admission read publishes the snapshot, records nothing
    assert not plate_outcomes.path().exists()
    tracker.answer = busy()
    ensure_room(tracker, 'worker')
    assert outcomes() == ['snapshot']


def test_busy_without_fresh_snapshot_records_unknown_busy():
    tracker = Tracker()
    tracker.answer = Answer.complete_read([row(1)], how='live')
    size(tracker, 'worker')
    age_snapshot(tracker, 'worker', 3600)
    tracker.answer = busy()
    with pytest.raises(CapacityUnknown, match='plate size UNKNOWN'):
        ensure_room(tracker, 'worker')
    assert outcomes() == ['unknown_busy']


def test_non_transient_failure_records_unknown_other():
    tracker = Tracker()
    tracker.answer = Answer.capped([], how='owner scope', caveat='truncated')
    with pytest.raises(CapacityUnknown):
        ensure_room(tracker, 'worker')
    assert outcomes() == ['unknown_other']


def test_unwritable_counter_never_changes_the_decision(monkeypatch, tmp_path):
    blocker = tmp_path / 'not-a-dir'
    blocker.write_text('')
    monkeypatch.setattr(plate_outcomes, 'path', lambda: blocker / 'x' / plate_outcomes.FILENAME)
    tracker = Tracker()
    tracker.answer = Answer.complete_read([row(1)], how='live')
    ensure_room(tracker, 'worker')  # admitted; the failed count is swallowed


def test_counts_window_rotation_and_cli(capsys):
    plate_outcomes.record('unknown_busy', 'worker', at=100.0)
    plate_outcomes.record('snapshot', 'worker', at=200.0)
    plate_outcomes.record('live', 'worker', at=300.0)
    assert plate_outcomes.counts(150.0) == {'snapshot': 1, 'live': 1}
    target = plate_outcomes.path()
    target.rename(target.with_name(plate_outcomes.FILENAME + '.1'))
    plate_outcomes.record('unknown_other', 'worker', at=400.0)
    assert plate_outcomes.counts(0.0) == {'unknown_busy': 1, 'snapshot': 1, 'live': 1, 'unknown_other': 1}
    assert plate_outcomes.main(['--since', '1970-01-01T00:05:01Z']) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed['live'], printed['unknown_other'], printed['unknown_busy']) == (0, 1, 0)
    assert oct(target.stat().st_mode & 0o777) == '0o600'


def test_unknown_outcome_name_is_rejected():
    with pytest.raises(ValueError):
        plate_outcomes.record('maybe', 'worker')


def test_environment_override_reaches_child_processes(tmp_path, monkeypatch):
    import subprocess
    import sys
    target = tmp_path / 'child.jsonl'
    monkeypatch.setenv('SHANTYTOWN_PLATE_OUTCOMES', str(target))
    subprocess.run([sys.executable, '-c',
                    'from shantytown import plate_outcomes; plate_outcomes.record("live", "w", at=1.0)'],
                   check=True)
    assert json.loads(target.read_text())['outcome'] == 'live'
