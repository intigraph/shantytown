from datetime import datetime, timezone
import json
from types import SimpleNamespace
import pytest
from shantytown import resume_rulings as rulings
from shantytown.answer import Answer
from shantytown.protocols import Agent

NOW = datetime(2026, 11, 6, 4, tzinfo=timezone.utc)
START = '2026-11-06T03:00:00Z'
UNTIL = '2026-11-07T04:00:00Z'
WAIT = dict(id='item-1', defer_until=UNTIL, notes='defer_provenance: ' + json.dumps(
    dict(actor='worker', set_at=START, until=UNTIL)))
CREW = [Agent('admin', role='administrator'), Agent('lead', role='lead'),
        Agent('worker', reports_to='lead')]
REG = SimpleNamespace(all=lambda: Answer.complete_read(CREW, how='fixture'),
                      get=lambda name: next(a for a in CREW if a.name == name))


def comment(outcome='granted', authority='admin', declared='2026-11-06T03:01:00Z',
            recorded='2026-11-06T03:01:01Z', **changes):
    row = dict(id=1, author=authority, created_at=recorded,
        text=f'resume-event-v1: activation:item-1 outcome={outcome} authority={authority} at={declared}')
    return row | changes


def evaluate(rows, **kw):
    return rulings.evaluate('activation', 'item-1', WAIT, NOW,
        show=lambda item: dict(id=item, assignee='worker'), comments=lambda item: rows,
        registry=kw.get('registry', REG))


@pytest.mark.parametrize('authority', ['admin', 'lead'])
def test_only_exact_post_deferral_configured_authority_grant_is_met(authority):
    assert evaluate([comment(authority=authority)])[0] is True


@pytest.mark.parametrize('outcome', ['denied', 'revoked'])
def test_denial_or_revocation_does_not_release(outcome):
    assert evaluate([comment(outcome=outcome)])[0] is False


def test_free_prose_and_wrong_target_are_not_a_marker():
    assert evaluate([comment(text='Admin approved activation; go ahead')])[0] is False
    assert evaluate([comment(text=comment()['text'].replace('item-1', 'item-2'))])[0] is False


def test_old_comments_and_fresh_quoted_timestamps_do_not_discharge_new_deferral():
    assert evaluate([comment(declared='2026-11-06T02:00:00Z', recorded='2026-11-06T02:00:01Z')])[0] is False
    assert evaluate([comment(recorded='2026-11-06T02:00:01Z')])[0] is False


@pytest.mark.parametrize('row', [comment(authority='worker'), comment(author='worker'),
    comment(declared='2026-11-06T04:01:00Z', recorded='2026-11-06T04:01:01Z'),
    comment(declared='2026-11-06T03:02:00Z'), comment(recorded='2026-11-06T03:10:00Z'),
    comment(id=None), comment(created_at=None), comment(text='resume-event-v1: malformed')])
def test_unreadable_spoofed_or_future_evidence_stays_unknown(row):
    assert evaluate([row])[0] is None


def test_newer_revocation_wins_and_empty_or_capped_inventories_are_distinct():
    grant = comment()
    revoked = comment(outcome='revoked', id=2, declared='2026-11-06T03:02:00Z', recorded='2026-11-06T03:02:01Z')
    assert evaluate([revoked, grant])[0] is False
    assert evaluate([])[0] is False
    assert evaluate([grant] * rulings.MAX_COMMENTS)[0] is None


def test_missing_authority_or_current_boundary_is_unknown():
    reg = SimpleNamespace(all=lambda: Answer.complete_read([], how='fixture'))
    assert evaluate([comment()], registry=reg)[0] is None
    assert rulings.evaluate('activation', 'item-1', WAIT | {'notes': ''}, NOW,
        show=lambda *a: pytest.fail('must reject before reads'), comments=lambda *a: [], registry=REG)[0] is None


def test_registered_kinds_require_a_day_even_without_wait_prose_or_with_window():
    from shantytown import deferrals, resume_kinds, deferral_waits
    from datetime import timedelta
    for kind in ('activation', 'ruling'):
        resume_kinds.validate(kind, 'item-1')
        cond = deferrals.Condition(kind, 'item-1')
        assert cond.testable()
        with pytest.raises(ValueError, match='24'):
            deferral_waits.validate('', '', cond, NOW + timedelta(hours=1), NOW, window=True)


def test_sweeper_integration_never_releases_unknown_or_denied_and_keeps_ask_labels():
    from shantytown import deferrals
    row = WAIT | dict(status='deferred', labels=['blocked:external'],
                     notes=WAIT['notes'] + '\nresume_when: activation:item-1')
    for verdict in (True, False, None):
        findings = deferrals.evaluate([row], NOW, ruling_reader=lambda *a: (verdict, 'fixture'))
        if verdict is False:
            assert not findings  # a known-unmet future wait needs no action
            continue
        finding, = findings
        assert finding.met is (verdict is True)
        if verdict is not True:
            assert not deferrals.can_release(row, finding, NOW)
    finding, = deferrals.evaluate([row], NOW, ruling_reader=lambda *a: (True, 'authorized'))
    assert not deferrals.can_release(row | {'labels': ['blocked:human']}, finding, NOW)
    unknown, = deferrals.evaluate([row], NOW)
    assert unknown.read_error and not unknown.met


@pytest.mark.parametrize('fresh_outcome', ['granted', 'revoked'])
def test_real_writer_reaches_scheduled_sweeper_and_fresh_revocation_prevents_release(tmp_path, monkeypatch, fresh_outcome):
    from datetime import timedelta
    from shantytown.dispatch import Dispatcher
    from shantytown.files import FilesRegistry, FilesTracker
    from shantytown.tmux import NullPanes
    from shantytown.notify import DeferralAlerter
    from shantytown import feed_check, deferral_notes, deferrals
    tracker = FilesTracker(tmp_path / 'items')
    tracker.update('item-1', title='fixture', status='open', assignee='worker', priority=1)
    until = (datetime.now(timezone.utc) + timedelta(hours=25)).strftime('%Y-%m-%dT%H:%M:%SZ')
    Dispatcher(FilesRegistry(tmp_path / 'crew'), tracker, NullPanes()).defer('item-1', 'external',
        'resume_when: activation:item-1', until=until, gate_authority='worker')
    row = json.loads(tracker._path('item-1').read_text()) | {'id': 'item-1'}
    provenance = deferral_notes.parse_provenance(row['notes'].splitlines()[-1])
    start = deferrals.parse_stamp(provenance['set_at'])
    at = (start + timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    recorded = (start + timedelta(minutes=1, seconds=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    calls = []
    def comments(item):
        calls.append(item)
        return [comment(outcome='granted' if len(calls) == 1 else fresh_outcome,
                        declared=at, recorded=recorded)]
    monkeypatch.setattr(feed_check, 'backend_adapter', lambda *a: SimpleNamespace(ruling_comments=comments))
    released = []
    DeferralAlerter(tmp_path, REG, NullPanes(), read=lambda: [row], show=lambda item: row,
        release=lambda item: released.append(item), now=start + timedelta(hours=26),
        push=lambda *a: None).sweep()
    assert len(calls) == 2
    assert released == (['item-1'] if fresh_outcome == 'granted' else [])


@pytest.mark.parametrize('doc', [
    {'comments': [], 'has_more': True}, {'comments': [], 'total': 1},
    {'comments': ['not metadata']}, 'not a page'])
def test_comment_adapter_cannot_silently_drop_capped_or_malformed_metadata(doc):
    import subprocess
    from shantytown.feed_check import TrackerAdapter
    tracker = SimpleNamespace(_bd_for=lambda *a: subprocess.CompletedProcess([], 0, json.dumps(doc), ''))
    adapter = TrackerAdapter.__new__(TrackerAdapter)
    adapter.tracker = tracker
    with pytest.raises(ValueError):
        adapter.ruling_comments('item-1')


def test_historical_malformed_marker_is_inert_but_duplicate_current_identity_is_unknown():
    old = comment(text='resume-event-v1: old malformed history', recorded='2026-11-06T02:00:00Z')
    assert evaluate([old, comment()])[0] is True
    assert evaluate([comment(), comment()])[0] is None


def test_ambiguous_crew_cards_or_missing_owner_lead_do_not_grant():
    for cards in (CREW + [CREW[0]], CREW[:2], [CREW[0], Agent('worker')]):
        reg = SimpleNamespace(all=lambda: Answer.complete_read(cards, how='fixture'))
        assert evaluate([comment()], registry=reg)[0] is None
