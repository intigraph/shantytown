"""Natural evidence proves a pair only with bounded, complete provenance."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from shantytown import deferrals, resume_events as events
from shantytown.dispatch import Dispatcher, DeferRefused, TrackerWriteLost
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.tmux import NullPanes

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
BINDING = events.Binding('fixture-1', 'producer-v1', 'host', 'unit', 'boot-1',
                         'window-1', NOW - timedelta(days=1), True)


def evidence():
    return dict(schema=1, item='fixture-1', producer='producer-v1', host='host',
                unit='unit', generation='boot-1', window='window-1',
                capture_start='2026-10-17T10:00:00Z',
                capture_end='2026-10-17T11:50:00Z',
                observed_at='2026-10-17T11:55:00Z',
                window_start='2026-10-17T10:10:00Z',
                window_end='2026-10-17T10:20:00Z', complete=True, gaps=[],
                sequence_start=1, sequence_end=2, events=[
                    dict(id='d', sequence=1, generation='boot-1', at='2026-10-17T10:15:00Z',
                         kind='soft-defer', natural=True),
                    dict(id='r', sequence=2, generation='boot-1', at='2026-10-17T10:25:00Z',
                         kind='recycle', natural=True, success=True)])


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(events, 'REGISTRY', {'fixture-v1': BINDING})
    monkeypatch.setenv('HOME', str(tmp_path))
    path = tmp_path / '.local/state/shantytown/resume-events/fixture-v1.json'
    path.parent.mkdir(parents=True)
    path.parent.chmod(0o700)
    path.write_text(json.dumps(evidence()))
    path.chmod(0o600)
    return path


def row(**kw):
    return dict(id='fixture-1', status='deferred',
                notes='resume_when: event:fixture-v1', **kw)


def test_real_bounded_reader_positive_and_absence(source):
    result = events.evaluate('fixture-v1', 'fixture-1', NOW)
    assert result.state == 'MET' and result.events == ('d', 'r')
    assert len(result.digest) == 64
    data = evidence()
    data.update(events=[], sequence_end=0)
    source.write_text(json.dumps(data))
    assert events.evaluate('fixture-v1', 'fixture-1', NOW).state == 'NOT_MET'


@pytest.mark.parametrize('kind', ['manual-restart', 'hard-override'])
def test_intervening_operation_disqualifies_pair(kind):
    data = evidence()
    data['events'].insert(1, dict(id='manual', sequence=2, generation='boot-1',
                         at='2026-10-17T10:18:00Z', kind=kind))
    data['events'][2]['sequence'] = 3
    data['sequence_end'] = 3
    assert events.decide(BINDING, data, NOW).state == 'NOT_MET'


@pytest.mark.parametrize('index,field,value', [
    (0, 'natural', False), (1, 'natural', False), (1, 'success', False),
    (0, 'at', '2026-10-17T10:05:00Z'), (1, 'at', '2026-10-17T10:19:00Z')])
def test_nonqualifying_complete_pair_is_not_met(index, field, value):
    data = evidence()
    data['events'][index][field] = value
    assert events.decide(BINDING, data, NOW).state == 'NOT_MET'


@pytest.mark.parametrize('field,value', [
    ('producer', 'other'), ('host', 'other'), ('unit', 'other'),
    ('item', 'other'), ('generation', 'other'), ('window', 'other'),
    ('complete', False), ('gaps', ['missing']), ('schema', True),
    ('sequence_end', 3), ('events', {}), ('observed_at', '2026-10-17T11:20:00Z'),
    ('observed_at', '2026-10-17T12:01:00Z'),
    ('capture_start', '2026-10-17T10:14:00Z'),
    ('window_end', '2026-10-17T10:09:00Z')])
def test_incomplete_untrusted_or_stale_evidence_unknown(field, value):
    data = evidence()
    data[field] = value
    assert events.decide(BINDING, data, NOW).state == 'UNKNOWN'


def test_invalid_rows_horizon_and_limits():
    for change in [dict(id='d'), dict(sequence=True), dict(kind='unknown'), dict(generation='new-boot'),
                   dict(at='2026-10-17T09:59:00Z'), dict(natural=1)]:
        data = evidence()
        data['events'][1].update(change)
        assert events.decide(BINDING, data, NOW).state == 'UNKNOWN'
    assert events.decide(replace(BINDING, not_before=NOW-timedelta(days=15)),
                         evidence(), NOW).state == 'UNKNOWN'
    data = evidence()
    data['events'] *= 501
    assert events.decide(BINDING, data, NOW).state == 'UNKNOWN'


@pytest.mark.parametrize('failure', ['missing', 'malformed', 'duplicate', 'nested', 'size',
                                    'mode', 'directory-mode', 'symlink', 'parent-symlink'])
def test_unreadable_invalid_or_unsafe_file_never_passes(source, failure):
    if failure == 'missing':
        source.unlink()
    elif failure == 'malformed':
        source.write_text('[]')
    elif failure == 'duplicate':
        source.write_text('{"schema":1,"schema":1}')
    elif failure == 'nested':
        source.write_text('[' * 2000 + '0' + ']' * 2000)
    elif failure == 'size':
        source.write_bytes(b' ' * (events.MAX_BYTES + 1))
    elif failure == 'mode':
        source.chmod(0o666)
    elif failure == 'directory-mode':
        source.parent.chmod(0o777)
    elif failure == 'symlink':
        other = source.with_suffix('.other')
        source.rename(other)
        source.symlink_to(other)
    else:
        parent = source.parent
        other = parent.with_name('other')
        parent.rename(other)
        parent.symlink_to(other, target_is_directory=True)
    assert events.evaluate('fixture-v1', 'fixture-1', NOW).state == 'UNKNOWN'


def test_disabled_registry_wrong_item_and_arbitrary_path_refused(source, monkeypatch):
    for identifier, item in [('fixture-v1', 'other'), ('../escape', 'fixture-1'),
                             ('http://host/path', 'fixture-1')]:
        assert events.evaluate(identifier, item, NOW).state == 'UNKNOWN'
    monkeypatch.setattr(events, 'REGISTRY', {'fixture-v1': replace(BINDING, accepted=False)})
    assert events.evaluate('fixture-v1', 'fixture-1', NOW).state == 'UNKNOWN'


def test_date_does_not_bypass_event_unknown_or_not_met(source):
    r = row(defer_until='2026-10-16T01:00:00Z')
    source.unlink()
    finding = deferrals.evaluate([r], NOW)[0]
    assert 'UNKNOWN' in finding.untestable and not finding.met
    assert not deferrals.can_release(r, finding, NOW)
    data = evidence()
    data['events'][1]['natural'] = False
    source.write_text(json.dumps(data))
    source.chmod(0o600)
    finding = deferrals.evaluate([r], NOW)[0]
    assert not finding.met and not finding.untestable
    assert not deferrals.can_release(r, finding, NOW)


def test_met_preserves_existing_judgment_and_date_gates(source):
    r = row()
    finding = deferrals.evaluate([r], NOW)[0]
    assert finding.met and deferrals.can_release(r, finding, NOW)
    for altered in [r | {'notes': r['notes']+'\noperator approval required'},
                    r | {'defer_until': '2026-10-18T00:00:00Z'},
                    r | {'notes': r['notes']+'\nresume_when: closed:other'},
                    r | {'labels': ['blocked:human']}]:
        found = deferrals.evaluate([altered], NOW)[0]
        assert not deferrals.can_release(altered, found, NOW)


def test_write_readback_and_disabled_binding_no_write(source, tmp_path, monkeypatch):
    tracker = FilesTracker(tmp_path / 'items')
    tracker.update('fixture-1', status='open', priority=2)
    dispatch = Dispatcher(FilesRegistry(tmp_path / 'crew'), tracker, NullPanes())
    dispatch.defer('fixture-1', 'external', 'resume_when: event:fixture-v1')
    stored = tracker.get('fixture-1')
    assert stored.status == 'deferred' and stored.notes == 'resume_when: event:fixture-v1'
    before = tracker._path('fixture-1').read_bytes()
    monkeypatch.setattr(events, 'REGISTRY', {'fixture-v1': replace(BINDING, accepted=False)})
    with pytest.raises(DeferRefused, match='disabled'):
        dispatch.defer('fixture-1', 'external', 'resume_when: event:fixture-v1')
    assert tracker._path('fixture-1').read_bytes() == before


def test_lost_event_marker_is_not_reported_as_verified(source, tmp_path):
    tracker = FilesTracker(tmp_path / 'items')
    tracker.update('fixture-1', status='open', priority=2)
    real = tracker.update
    def drop_notes(identifier, **fields):
        fields.pop('defer_reason', None)
        return real(identifier, **fields)
    tracker.update = drop_notes
    dispatch = Dispatcher(FilesRegistry(tmp_path / 'crew'), tracker, NullPanes())
    with pytest.raises(TrackerWriteLost):
        dispatch.defer('fixture-1', 'external', 'resume_when: event:fixture-v1')
    assert tracker.get('fixture-1').status == 'open'


def test_scheduled_release_rechecks_evidence_and_reads_back(source, tmp_path, monkeypatch):
    from tests.test_deferrals import MechanicalHarness
    # The harness fixes its clock; feed the evaluator's clock into our evidence
    # adapter while keeping its normal file reader and registry validation.
    real = events.evaluate
    monkeypatch.setattr(events, 'evaluate', lambda key, item, _now: real(key, item, NOW))
    harness = MechanicalHarness(tmp_path, row())
    harness.alerter.sweep()
    assert harness.releases == ['fixture-1']
    assert any('verified open' in line for line in harness.logs)
    harness = MechanicalHarness(tmp_path / 'again', row())
    calls = 0
    def changed(key, item, _now):
        nonlocal calls
        calls += 1
        result = real(key, item, NOW)
        if calls == 1:
            source.unlink()
        return result
    monkeypatch.setattr(events, 'evaluate', changed)
    harness.alerter.sweep()
    assert harness.releases == [] and calls == 2
