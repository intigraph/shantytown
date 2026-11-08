"""Producer facts wake a waiter; a date or unavailable producer cannot."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from shantytown import deferrals
from shantytown import resume_producers as events
from shantytown.deferral_notes import provenance

NOW = datetime(2026, 11, 8, 18, tzinfo=timezone.utc)
CLASS = '13f8331307c386a4e6eb2a65'


def row(kind='recurring-quiet', arg=CLASS):
    return dict(id='item-1', status='deferred', labels=['blocked:external'],
                defer_until='2026-11-09T18:00:00Z',
                notes=f'resume_when: {kind}:{arg}\n' + provenance(
                    'wu', '2026-11-08T17:00:00Z', '2026-11-09T18:00:00Z'))


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    path = tmp_path / '.local/state/recurring-alarms/state.json'
    path.parent.mkdir(parents=True, mode=0o700)
    data = dict(version=1, last_census=NOW.timestamp(), classes={CLASS: dict(
        bead='item-1', active=False, quiet_since=(NOW-timedelta(days=14)).timestamp(),
        last_fired=(NOW-timedelta(days=15)).timestamp())})
    def write():
        path.write_text(json.dumps(data)); path.chmod(0o600)
    write()
    return path, data, write


def test_quiet_and_refire_are_distinct_readiness_events(state):
    _, data, write = state
    assert events.evaluate('recurring-quiet', CLASS, row(), NOW).state == 'MET'
    data['classes'][CLASS]['quiet_since'] = NOW.timestamp()-10
    write()
    assert events.evaluate('recurring-quiet', CLASS, row(), NOW).state == 'NOT_MET'
    data['classes'][CLASS].update(active=True, last_fired=NOW.timestamp()-1)
    write()
    assert events.evaluate('recurring-quiet', CLASS, row(), NOW).state == 'MET'


@pytest.mark.parametrize('change', ['stale', 'missing', 'foreign', 'future', 'boolean', 'unsafe', 'link'])
def test_unreadable_or_untrusted_state_is_unknown(state, change):
    path, data, write = state
    if change == 'stale': data['last_census'] = NOW.timestamp()-601
    if change == 'missing': data['classes'][CLASS].pop('quiet_since')
    if change == 'foreign': data['classes'][CLASS]['bead'] = 'other'
    if change == 'future': data['last_census'] = NOW.timestamp()+1
    if change == 'boolean': data['classes'][CLASS]['last_fired'] = True
    write()
    if change == 'unsafe': path.chmod(0o666)
    if change == 'link':
        target = path.with_suffix('.real'); path.rename(target); path.symlink_to(target)
    assert events.evaluate('recurring-quiet', CLASS, row(), NOW).state == 'UNKNOWN'


def test_absent_quiet_is_unmet_only_with_authoritative_active_census(state):
    _, data, write = state
    data['classes'][CLASS].pop('quiet_since')
    data['classes'][CLASS]['active'] = True
    write()
    assert events.evaluate('recurring-quiet', CLASS, row(), NOW).state == 'NOT_MET'
    data['last_census'] = 0; write()
    assert events.evaluate('recurring-quiet', CLASS, row(), NOW).state == 'UNKNOWN'


def test_refire_needs_one_valid_deferral_boundary(state):
    _, data, write = state
    data['classes'][CLASS].update(active=True, last_fired=NOW.timestamp()-1); write()
    r = row(); r['notes'] = r['notes'].splitlines()[0]
    assert events.evaluate('recurring-quiet', CLASS, r, NOW).state == 'UNKNOWN'


def test_sweeper_releases_real_event_before_backstop_and_retains_unknown(state):
    r = row()
    finding, = deferrals.evaluate([r], NOW)
    assert finding.met and deferrals.can_release(r, finding, NOW)
    path, _, _ = state; path.unlink()
    r['defer_until'] = '2026-11-01T18:00:00Z'
    finding, = deferrals.evaluate([r], NOW)
    assert finding.read_error and not deferrals.can_release(r, finding, NOW)


@pytest.mark.parametrize('kind,arg', [
    ('recurring-quiet', '../../state'), ('recurring-quiet', CLASS+'x'),
    ('evidence-count', 'unknown>=20'), ('evidence-count', 'fixture>=0'),
    ('evidence-count', 'fixture>=999999999999999999999999')])
def test_writer_validation_rejects_paths_and_unregistered_counters(kind, arg):
    with pytest.raises(ValueError): events.validate(kind, arg)


def test_no_registered_counter_never_turns_into_zero_or_ready():
    result = events.evaluate('evidence-count', 'unknown>=20', row(), NOW)
    assert result.state == 'UNKNOWN'


def test_one_snapshot_per_pass_and_fresh_read_after_unavailability(state, monkeypatch):
    path, data, write = state
    other = '1' * 24
    data['classes'][other] = dict(data['classes'][CLASS], bead='item-2')
    write()
    second = row(arg=other); second['id'] = 'item-2'
    rows = [row(), second]
    reads = []
    original = events.read_producer_file
    def counted(*args):
        reads.append(args[0])
        return original(*args)
    monkeypatch.setattr(events, 'read_producer_file', counted)
    assert all(f.met for f in deferrals.evaluate(rows, NOW))
    assert len(reads) == 1
    path.unlink()
    assert all(f.read_error for f in deferrals.evaluate(rows, NOW))
    assert len(reads) == 2
    write()
    assert all(f.met for f in deferrals.evaluate(rows, NOW))
    assert len(reads) == 3


@pytest.fixture
def counter(monkeypatch):
    observation = events.CountObservation(tuple(map(str, range(19))), 'window-v2', NOW, True, True)
    values = [observation]
    monkeypatch.setattr(events, 'COUNTERS', {'fixture': events.Counter(
        'item-1', 'window-v2', lambda: values[0], timedelta(minutes=10))})
    return values


def test_registered_counter_threshold_and_identity_reset(counter):
    from dataclasses import replace
    r = row('evidence-count', 'fixture>=20')
    assert events.evaluate('evidence-count', 'fixture>=20', r, NOW).state == 'NOT_MET'
    counter[0] = replace(counter[0], candidate_ids=tuple(map(str, range(20))))
    assert events.evaluate('evidence-count', 'fixture>=20', r, NOW).state == 'MET'
    # Old corpus evidence never carries across a changed measurement identity.
    counter[0] = replace(counter[0], identity='old-window')
    assert events.evaluate('evidence-count', 'fixture>=20', r, NOW).state == 'UNKNOWN'


@pytest.mark.parametrize('field,value', [('complete', False), ('candidate_ids', True),
    ('candidate_ids', ('same', 'same')), ('required_coverage', None),
    ('observed_at', NOW-timedelta(minutes=11)),
    ('observed_at', NOW+timedelta(seconds=1))])
def test_counter_incomplete_or_stale_is_unknown(counter, field, value):
    from dataclasses import replace
    counter[0] = replace(counter[0], **{field: value})
    assert events.evaluate('evidence-count', 'fixture>=20', row(), NOW).state == 'UNKNOWN'


def test_enough_candidates_without_required_coverage_stays_parked(counter):
    from dataclasses import replace
    counter[0] = replace(counter[0], candidate_ids=tuple(map(str, range(20))), required_coverage=False)
    assert events.evaluate('evidence-count', 'fixture>=20', row(), NOW).state == 'NOT_MET'


def test_registered_counter_cannot_write_an_unreachable_threshold(counter):
    with pytest.raises(ValueError):
        events.validate('evidence-count', 'fixture>=10001')


def test_complete_empty_inventory_is_unmet_not_an_unknown_read(counter):
    from dataclasses import replace
    counter[0] = replace(counter[0], candidate_ids=(), required_coverage=False)
    assert events.evaluate('evidence-count', 'fixture>=20', row(), NOW).state == 'NOT_MET'


def test_counter_reader_failure_and_foreign_item_are_unknown(counter, monkeypatch):
    from dataclasses import replace
    r = row(); r['id'] = 'other'
    assert events.evaluate('evidence-count', 'fixture>=20', r, NOW).state == 'UNKNOWN'
    def unavailable(): raise OSError('fixture unavailable')
    monkeypatch.setitem(events.COUNTERS, 'fixture', replace(
        events.COUNTERS['fixture'], reader=unavailable))
    assert events.evaluate('evidence-count', 'fixture>=20', row(), NOW).state == 'UNKNOWN'


@pytest.mark.parametrize('kind,arg', [('recurring-quiet', CLASS),
                                      ('evidence-count', 'fixture>=20')])
def test_normal_writer_and_three_unmet_sweeps(state, counter, tmp_path, kind, arg):
    from shantytown.dispatch import Dispatcher
    from shantytown.files import FilesRegistry, FilesTracker
    from shantytown.tmux import NullPanes
    tracker = FilesTracker(tmp_path / 'items')
    tracker.update('item-1', title='natural evidence', status='open', assignee='wu', priority=2)
    writer = Dispatcher(FilesRegistry(tmp_path / 'crew'), tracker, NullPanes())
    writer.defer('item-1', 'external', f'resume_when: {kind}:{arg}', until='2099-01-01')
    stored = tracker.get('item-1')
    assert stored.status == 'deferred'
    # These are controlled sweep fixtures, not the required natural haul proof.
    from dataclasses import replace
    from shantytown.deferral_notes import parse_provenance
    start = datetime.fromisoformat(parse_provenance(stored.notes.splitlines()[-1])['set_at'])
    _, data, write = state
    data['last_census'] = start.timestamp()
    data['classes'][CLASS].update(quiet_since=start.timestamp()-10,
                                 last_fired=start.timestamp()-15*86400)
    write()
    counter[0] = replace(counter[0], observed_at=start)
    for offset in (0, 60, 120):
        at = start+timedelta(seconds=offset)
        r = dict(id=stored.id, status=stored.status, notes=stored.notes,
                 labels=stored.labels, defer_until=stored.defer_until)
        assert deferrals.evaluate([r], at) == []
        assert tracker.get('item-1').status == 'deferred'
