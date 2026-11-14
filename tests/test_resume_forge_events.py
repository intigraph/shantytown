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
    original = tracker._path('item-1').read_bytes()
    for condition in ['pr-merged:github/example/project#123',
                      'ci-terminal:github/example/project@' + SHA]:
        with pytest.raises(DeferRefused, match='stay in_progress'):
            dispatch.defer('item-1', 'external', 'resume_when: ' + condition, until=until)
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
    exhausted = [f for f in findings if not f.met]
    assert len(exhausted) == 1
    assert exhausted[0].read_error and exhausted[0].read_deferred


def test_whole_sweeper_shares_fresh_read_budget_for_duplicate_fact_waits(tmp_path, monkeypatch):
    import json
    import subprocess
    from shantytown import deferral_notes
    from shantytown.files import FilesRegistry
    from shantytown.notify import DeferralAlerter
    from shantytown.tmux import NullPanes
    until = '2026-11-06T03:00:00Z'
    notes = ('resume_when: pr-merged:github/example/project#123\n' +
             deferral_notes.provenance('worker', '2026-11-04T03:00:00Z', until))
    rows = [dict(id='item-' + str(i), title='fixture', priority=1, assignee='worker',
                 status='deferred', defer_until=until, labels=['blocked:external'], notes=notes)
            for i in range(30)]
    by_id = {row['id']: row for row in rows}
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(dict(
            number=123, merged=True, state='closed', merged_at='2026-11-06T03:01:00Z')), '')
    monkeypatch.setattr(events.subprocess, 'run', run)
    released = []
    DeferralAlerter(tmp_path, FilesRegistry(tmp_path / 'crew'), NullPanes(), read=lambda: rows,
        show=lambda item: by_id[item], release=lambda item: released.append(item),
        now=datetime(2026, 11, 6, 4, tzinfo=timezone.utc), push=lambda *a: None).sweep()
    assert len(calls) == 1 + events.MAX_READS  # one deduplicated candidate + fresh phase
    assert len(released) == events.MAX_READS


@pytest.mark.parametrize('event,trigger', [('', 'workflow_dispatch'), ('push', 'schedule')])
def test_live_forgejo_trigger_identity_is_not_the_legacy_event_field(event, trigger):
    def read(forge, repo, path):
        if path.startswith('actions/runs?'):
            return {'total_count': 1, 'workflow_runs': [dict(id=1, workflow_id='ci.yml',
                event=event, trigger_event=trigger, commit_sha=SHA, status='success')]}
        return []
    assert events.evaluate('ci-terminal', 'forgejo/example/project@' + SHA, read=read)[0] is True


def test_validated_active_workflow_is_a_sufficient_unmet_witness_without_extra_reads():
    calls = []
    def read(*args):
        calls.append(args)
        assert args[-1].startswith('actions/runs?')
        return {'total_count': 1, 'workflow_runs': [dict(id=1, workflow_id=2,
            event='push', head_sha=SHA, status='in_progress', conclusion=None)]}
    assert events.evaluate('ci-terminal', CI, read=read)[0] is False
    assert len(calls) == 1


def test_active_witness_does_not_mask_invalid_or_foreign_workflow_inventory():
    rows = [dict(id=1, workflow_id=2, event='push', head_sha=SHA,
                 status='in_progress', conclusion=None),
            dict(id=2, workflow_id=3, event='push', head_sha='b' * 40,
                 status='completed', conclusion='success')]
    assert events.evaluate('ci-terminal', CI, read=lambda *a:
        {'total_count': 2, 'workflow_runs': rows})[0] is None


def test_forgejo_running_is_known_unmet_not_a_parser_failure():
    def read(*args):
        assert args[-1].startswith('actions/runs?')
        return {'total_count': 1, 'workflow_runs': [dict(id=1, workflow_id='ci.yml',
            event='', trigger_event='push', commit_sha=SHA, status='running')]}
    assert events.evaluate('ci-terminal', 'forgejo/example/project@' + SHA, read=read)[0] is False


def test_forgejo_default_fifty_row_status_page_cannot_hide_a_later_pending_context():
    calls = []
    def read(forge, repo, path):
        calls.append(path)
        if path.startswith('actions/runs?'):
            return {'total_count': 1, 'workflow_runs': [dict(id=1, workflow_id=2,
                event='push', trigger_event='push', commit_sha=SHA, status='success')]}
        if 'page=1' in path:
            return [dict(id=i + 2, context='finished-' + str(i), status='success') for i in range(50)]
        assert 'page=2' in path
        return [dict(id=100, context='late-visible', status='pending')]
    assert events.evaluate('ci-terminal', 'forgejo/example/project@' + SHA, read=read)[0] is False
    assert len(calls) == 3


def test_repeated_or_capped_status_pages_remain_unknown():
    rows = [dict(id=i + 2, context='finished-' + str(i), status='success') for i in range(50)]
    def read(forge, repo, path):
        if path.startswith('actions/runs?'):
            return {'total_count': 1, 'workflow_runs': [dict(id=1, workflow_id=2,
                event='push', commit_sha=SHA, status='success')]}
        return rows
    assert events.evaluate('ci-terminal', 'forgejo/example/project@' + SHA, read=read)[0] is None


def test_budgeted_fact_rotation_eventually_observes_every_target_without_mutating_rows(monkeypatch):
    import copy
    import json
    import subprocess
    from datetime import timedelta
    calls = []
    def run(argv, **kwargs):
        number = int(argv[-1].rsplit('/', 1)[1])
        calls.append(number)
        return subprocess.CompletedProcess(argv, 0, json.dumps(dict(
            number=number, merged=True, state='closed', merged_at='2026-11-06T03:00:00Z')), '')
    monkeypatch.setattr(events.subprocess, 'run', run)
    rows = [dict(id='item-' + str(i), status='deferred', labels=[],
                 notes='resume_when: pr-merged:github/example/project#' + str(i + 1))
            for i in range(7)]
    original = copy.deepcopy(rows)
    observed = set()
    now = datetime(2026, 11, 6, 4, tzinfo=timezone.utc)
    for slot in range(7):
        reader = events.Reader()
        reader.remaining = 2
        before = len(calls)
        findings = deferrals.evaluate(rows, now + timedelta(minutes=5 * slot), forge_reader=reader)
        assert len(calls) - before <= 2
        observed.update(f.bead for f in findings if f.met)
        skipped = [f for f in findings if not f.met]
        assert skipped and all(f.read_error and f.read_deferred for f in skipped)
        assert all(not deferrals.can_release(rows[int(f.bead.split('-')[1])], f, now)
                   for f in skipped)
    assert observed == {row['id'] for row in rows}
    assert rows == original


def test_budget_skips_preserve_prior_failure_counts_in_actual_sweeper(tmp_path, monkeypatch):
    import json
    import subprocess
    from shantytown.files import FilesRegistry
    from shantytown.notify import DeferralAlerter
    from shantytown.tmux import NullPanes
    monkeypatch.setattr(events, 'MAX_READS', 1)
    def run(argv, **kwargs):
        number = int(argv[-1].rsplit('/', 1)[1])
        return subprocess.CompletedProcess(argv, 0, json.dumps(dict(
            number=number, merged=True, state='closed', merged_at='2026-11-06T03:00:00Z')), '')
    monkeypatch.setattr(events.subprocess, 'run', run)
    rows = [dict(id='item-' + str(i), title='fixture', status='deferred', labels=['blocked:human'],
                 notes='resume_when: pr-merged:github/example/project#' + str(i + 1))
            for i in range(4)]
    now = datetime(2026, 11, 6, 4, tzinfo=timezone.utc)
    findings = deferrals.evaluate(rows, now)
    skipped = {f.bead for f in findings if f.read_deferred}
    path = tmp_path / 'notify/deferral-retries.json'
    path.parent.mkdir()
    path.write_text(json.dumps({row['id']: 2 for row in rows}))
    logs = []
    for _ in range(3):
        DeferralAlerter(tmp_path, FilesRegistry(tmp_path / 'crew'), NullPanes(),
            read=lambda: rows, now=now, push=lambda *a: None, log=logs.append).sweep()
        current = json.loads(path.read_text())
        assert all(current[item] == 2 for item in skipped)
    assert any('observation budget deferred; retains hold' in line for line in logs)
    assert not any('read/release retry pending' in line for line in logs)


def test_status_inventory_page_bound_is_still_unknown():
    def read(forge, repo, path):
        if path.startswith('actions/runs?'):
            return {'total_count': 1, 'workflow_runs': [dict(id=1, workflow_id=2,
                event='push', commit_sha=SHA, status='success')]}
        page = int(path.rsplit('page=', 1)[1])
        return [dict(id=page * 100 + i, context=str(page * 100 + i), status='success')
                for i in range(50)]
    assert events.evaluate('ci-terminal', 'forgejo/example/project@' + SHA, read=read)[0] is None
