"""Exact forge facts unblock event waits without turning UNKNOWN into release."""
from datetime import datetime, timezone
import pytest
from shantytown import deferrals, resume_kinds


def test_new_forge_kinds_are_registered_and_validated():
    for kind, arg in [('pr-merged', 'github/example/project#123'),
                      ('ci-terminal', 'github/example/project@' + 'a' * 40)]:
        resume_kinds.validate(kind, arg)
        assert deferrals.Condition(kind, arg).testable()


def test_new_kinds_always_require_a_day_backstop():
    from shantytown.deferral_waits import validate
    from datetime import timedelta
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    cond = deferrals.Condition('pr-merged', 'github/example/project#123')
    for window in (False, True):
        with pytest.raises(ValueError, match='24'):
            validate('resume_when: ' + cond.render(), '', cond,
                     now + timedelta(hours=1), now, window=window)
    validate('resume_when: ' + cond.render(), '', cond,
             now + timedelta(hours=24), now)

from shantytown import resume_forge_events as events
SHA = 'a' * 40
CI = 'github/example/project@' + SHA


def fake_ci(*, run_status='completed', conclusion='failure', checks=None, statuses=None):
    def read(forge, repo, path):
        assert (forge, repo) == ('github', 'example/project')
        if path.startswith('actions/runs?'):
            return {'total_count': 1, 'workflow_runs': [dict(id=5, workflow_id=2,
                event='pull_request', head_sha=SHA, status=run_status, conclusion=conclusion)]}
        if '/check-runs?' in path:
            values = checks or []
            return {'total_count': len(values), 'check_runs': values}
        assert path.startswith('commits/' + SHA + '/statuses?')
        return statuses or []
    return read


@pytest.mark.parametrize('forge', ['github', 'forgejo'])
def test_pr_only_merge_not_close_is_met(forge):
    arg = forge + '/example/project#123'
    for merged, state, at, want in [(False, 'open', None, False),
                                    (False, 'closed', None, False),
                                    (True, 'closed', '2026-11-06T03:00:00Z', True)]:
        assert events.evaluate('pr-merged', arg, read=lambda *a: dict(
            number=123, merged=merged, state=state, merged_at=at))[0] is want
    for doc in [{}, {'number': 124, 'state': 'closed', 'merged': True},
                {'number': 123, 'state': 'open', 'merged': True},
                {'number': 123, 'state': 'closed', 'merged': 'true'}]:
        assert events.evaluate('pr-merged', arg, read=lambda *a: doc)[0] is None


@pytest.mark.parametrize('conclusion', ['success', 'failure', 'cancelled', 'skipped', 'timed_out'])
def test_terminal_is_any_conclusion_and_never_green_approval(conclusion):
    assert events.evaluate('ci-terminal', CI, read=fake_ci(conclusion=conclusion))[0] is True


@pytest.mark.parametrize('status', ['queued', 'in_progress', 'waiting', 'pending', 'requested'])
def test_any_active_workflow_keeps_wait(status):
    assert events.evaluate('ci-terminal', CI, read=fake_ci(run_status=status, conclusion=None))[0] is False


def test_check_run_and_status_queues_cannot_hide_behind_finished_workflow():
    check = dict(id=9, head_sha=SHA, status='queued', conclusion=None)
    assert events.evaluate('ci-terminal', CI, read=fake_ci(checks=[check]))[0] is False
    statuses = [dict(id=9, context='build', state='pending'), dict(id=8, context='build', state='success')]
    assert events.evaluate('ci-terminal', CI, read=fake_ci(statuses=statuses))[0] is False
    statuses.reverse()
    assert events.evaluate('ci-terminal', CI, read=fake_ci(statuses=statuses))[0] is False


def test_absent_malformed_failed_or_truncated_ci_is_unknown():
    for read in [lambda *a: {}, lambda *a: {'total_count': 0, 'workflow_runs': []},
                 lambda *a: {'total_count': 101, 'workflow_runs': [{}] * 100},
                 lambda *a: (_ for _ in ()).throw(OSError('secret transport output')),
                 fake_ci(run_status='unknown'), fake_ci(conclusion=None),
                 fake_ci(checks=[dict(id=2, head_sha='b' * 40, status='completed', conclusion='success')])]:
        result = events.evaluate('ci-terminal', CI, read=read)
        assert result[0] is None
        assert 'secret' not in result[1]


@pytest.mark.parametrize('kind,arg', [
    ('pr-merged', 'github/example/project#0'), ('pr-merged', 'github/example/project#1;id'),
    ('pr-merged', 'evil/example/project#1'), ('pr-merged', 'github/../project#1'),
    ('ci-terminal', 'github/example/project@short'),
    ('ci-terminal', 'github/example/project@' + 'a' * 40 + '/extra')])
def test_invalid_marker_never_reads(kind, arg):
    seen = []
    assert events.evaluate(kind, arg, read=lambda *a: seen.append(a))[0] is None
    assert not seen


def test_reader_budget_exhaustion_is_unknown_without_transport(monkeypatch):
    reader = events.Reader()
    reader.remaining = 0
    monkeypatch.setattr(events.subprocess, 'run', lambda *a, **k: pytest.fail('no request allowed'))
    assert events.evaluate('ci-terminal', CI, read=reader)[0] is None


def test_sweeper_deduplicates_fact_reads_and_keeps_unknown_unreleasable(monkeypatch):
    seen = []
    monkeypatch.setattr(events.Reader, '__call__', lambda self, *a: seen.append(a) or dict(
        number=123, merged=True, state='closed', merged_at='2026-11-06T03:00:00Z'))
    now = datetime(2026, 11, 6, 4, tzinfo=timezone.utc)
    rows = [dict(id='item-' + str(i), status='deferred', notes='resume_when: pr-merged:github/example/project#123',
                 labels=[]) for i in range(2)]
    findings = deferrals.evaluate(rows, now)
    assert len(findings) == 2 and all(f.met for f in findings)
    assert len(seen) == 1
    monkeypatch.setattr(events.Reader, '__call__', lambda *a: (_ for _ in ()).throw(OSError()))
    findings = deferrals.evaluate(rows, now)
    assert all(f.read_error and f.untestable and not deferrals.can_release(r, f, now)
               for r, f in zip(rows, findings))


def test_dispatcher_records_event_and_backstop_and_refuses_bad_input_without_writes(tmp_path):
    from datetime import timedelta
    from shantytown.dispatch import Dispatcher, DeferRefused
    from shantytown.files import FilesRegistry, FilesTracker
    from shantytown.tmux import NullPanes
    tracker = FilesTracker(tmp_path / 'items')
    tracker.update('item-1', title='wait for exact PR', status='open', assignee='worker', priority=1)
    dispatch = Dispatcher(FilesRegistry(tmp_path / 'crew'), tracker, NullPanes())
    until = (datetime.now(timezone.utc) + timedelta(hours=25)).strftime('%Y-%m-%dT%H:%M:%SZ')
    dispatch.defer('item-1', 'external', 'resume_when: pr-merged:github/example/project#123', until=until)
    item = tracker.get('item-1')
    assert item.status == 'deferred' and item.defer_until == until
    assert deferrals.parse_condition(item.notes).render() == 'pr-merged:github/example/project#123'
    original = tracker._path('item-1').read_bytes()
    with pytest.raises(DeferRefused):
        dispatch.defer('item-1', 'external', 'resume_when: ci-terminal:github/example/project@short', until=until)
    assert tracker._path('item-1').read_bytes() == original


@pytest.mark.parametrize('state', ['success', 'failure', 'cancelled', 'skipped', 'waiting'])
def test_forgejo_native_run_states_are_normalized(state):
    def read(forge, repo, path):
        assert forge == 'forgejo'
        if path.startswith('actions/runs?'):
            return {'total_count': 1, 'workflow_runs': [dict(id=1, workflow_id=2,
                event='push', commit_sha=SHA, status=state)]}
        return []
    assert events.evaluate('ci-terminal', 'forgejo/example/project@' + SHA,
                           read=read)[0] is (state != 'waiting')


def test_github_transport_is_fixed_read_only_and_shared_pass_budget_is_real(monkeypatch):
    import json
    import subprocess
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        assert argv[:4] == ['gh', 'api', '--method', 'GET']
        assert kwargs['timeout'] == events.TIMEOUT
        number = int(argv[-1].rsplit('/', 1)[1])
        return subprocess.CompletedProcess(argv, 0, json.dumps(dict(
            number=number, merged=True, state='closed', merged_at='2026-11-06T03:00:00Z')), '')
    monkeypatch.setattr(events.subprocess, 'run', run)
    rows = [dict(id='item-' + str(i), status='deferred', labels=[],
                 notes='resume_when: pr-merged:github/example/project#' + str(i + 1))
            for i in range(events.MAX_READS + 1)]
    findings = deferrals.evaluate(rows, datetime(2026, 11, 6, 4, tzinfo=timezone.utc))
    assert len(calls) == events.MAX_READS
    assert sum(f.met for f in findings) == events.MAX_READS
    exhausted = next(f for f in findings if f.bead == 'item-' + str(events.MAX_READS))
    assert exhausted.read_error and not exhausted.met
