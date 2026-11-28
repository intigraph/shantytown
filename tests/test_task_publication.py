"""Real disposable Git refs/hooks; only forge metadata and URL identity are fake."""
import subprocess
from pathlib import Path

import pytest

from shantytown import ephemeral as eph, task_publication as pub


def git(*args):
    return subprocess.run(['git', '-c', 'maintenance.auto=false', '-c', 'gc.auto=0', *map(str, args)],
                          capture_output=True, text=True, timeout=30)


@pytest.fixture
def repair(tmp_path):
    remote, ws = tmp_path / 'remote.git', tmp_path / 'work'
    assert git('init', '--bare', remote).returncode == 0
    assert git('clone', remote, ws).returncode == 0
    for key, value in [('user.name', 'Fixture'), ('user.email', 'fixture@example.invalid')]:
        assert git('-C', ws, 'config', key, value).returncode == 0
    assert git('-C', ws, 'switch', '-c', 'main').returncode == 0
    file = ws / 'source'
    file.write_text('base')
    assert git('-C', ws, 'add', 'source').returncode == 0
    assert git('-C', ws, 'commit', '-m', 'base').returncode == 0
    base = git('-C', ws, 'rev-parse', 'HEAD').stdout.strip()
    assert git('-C', ws, 'switch', '-c', 'feature/fix').returncode == 0
    file.write_text('PR baseline')
    assert git('-C', ws, 'commit', '-am', 'PR baseline').returncode == 0
    tip = git('-C', ws, 'rev-parse', 'HEAD').stdout.strip()
    assert git('-C', ws, 'push', 'origin', 'main', 'feature/fix').returncode == 0
    assert git('-C', ws, 'switch', '-c', 'wt/eph-task-abc123').returncode == 0
    file.write_text('tested fix')
    assert git('-C', ws, 'commit', '-am', 'tested fix').returncode == 0
    head = git('-C', ws, 'rev-parse', 'HEAD').stdout.strip()
    info = dict(number=7, state='open', merged=False,
                head=dict(ref='feature/fix', sha=tip, repo=dict(full_name='o/n')),
                base=dict(ref='main', repo=dict(full_name='o/n')))
    rec = dict(name='eph-task-abc123', job='task', state=eph.LIVE, workspace=str(ws), repo='o/n', pr=7)
    calls = []
    def run(*args):
        calls.append(args)
        if args[2:4] == ('remote', 'get-url'):
            return subprocess.CompletedProcess(args, 0, 'https://github.com/o/n.git\n', '')
        return git(*args)
    return rec, head, info, run, calls, remote, base


def test_publishes_actual_pr_ref_not_job_branch_and_leaves_main(repair):
    rec, head, info, run, calls, remote, base = repair
    result = pub.publish(rec, head, gh=lambda _: info, git=run)
    assert result == dict(repo='o/n', pr=7, branch='feature/fix', head=head, verified=True)
    assert git('--git-dir', remote, 'rev-parse', 'refs/heads/feature/fix').stdout.strip() == head
    assert git('--git-dir', remote, 'rev-parse', 'refs/heads/main').stdout.strip() == base
    pushes = [c for c in calls if c[2] == 'push']
    assert len(pushes) == 1 and pushes[0][-1] == head + ':refs/heads/feature/fix'
    assert all('--force' not in c and '--no-verify' not in c for c in calls)


@pytest.mark.parametrize('fault', ['hook', 'dirty', 'untracked', 'wrong-head', 'fork', 'base', 'diverged', 'moved', 'push-url'])
def test_unsafe_publication_never_updates_pr(repair, fault):
    rec, head, info, run, calls, remote, base = repair
    tip = info['head']['sha']
    if fault == 'hook':
        hook = Path(rec['workspace']) / '.git' / 'hooks' / 'pre-push'
        hook.write_text('#!/bin/sh\nexit 1\n'); hook.chmod(0o755)
    elif fault == 'dirty':
        (Path(rec['workspace']) / 'source').write_text('untested')
    elif fault == 'untracked':
        (Path(rec['workspace']) / 'untested-new-source').write_text('uncommitted')
    elif fault == 'wrong-head': head = 'a' * 40
    elif fault == 'fork': info['head']['repo']['full_name'] = 'other/n'
    elif fault == 'base': info['head']['ref'] = 'main'
    elif fault == 'diverged':
        tree = git('-C', rec['workspace'], 'rev-parse', tip + '^{tree}').stdout.strip()
        tip = git('-C', rec['workspace'], 'commit-tree', tree, '-p', tip, '-m', 'parallel fix').stdout.strip()
        assert git('-C', rec['workspace'], 'push', 'origin', tip + ':refs/heads/feature/fix').returncode == 0
        info['head']['sha'] = tip
    elif fault == 'push-url':
        original = run
        def run(*args):
            if args[2:6] == ('remote', 'get-url', '--push', '--all'):
                return subprocess.CompletedProcess(args, 0, 'https://github.com/other/n.git\n', '')
            return original(*args)
    count = [0]
    def gh(_):
        count[0] += 1
        if fault == 'moved' and count[0] > 1:
            return dict(info, head=dict(info['head'], ref='other-branch'))
        return info
    with pytest.raises(eph.Refused):
        pub.publish(rec, head, gh=gh, git=run)
    assert git('--git-dir', remote, 'rev-parse', 'refs/heads/feature/fix').stdout.strip() == tip


def test_lost_push_reply_is_unknown_and_does_not_retry(repair):
    rec, head, info, run, calls, remote, _ = repair
    def lost(*args):
        result = run(*args)
        if args[2] == 'push':
            assert result.returncode == 0
            raise subprocess.TimeoutExpired('git push', 60)
        return result
    with pytest.raises(eph.Refused, match='acknowledgement UNKNOWN'):
        pub.publish(rec, head, gh=lambda _: info, git=lost)
    assert len([c for c in calls if c[2] == 'push']) == 1
    assert git('--git-dir', remote, 'rev-parse', 'refs/heads/feature/fix').stdout.strip() == head


def test_publish_cli_is_bound_to_its_live_task_identity(repair, monkeypatch):
    from shantytown import cli
    from test_ephemeral import _st
    rec, head, info, run, calls, remote, _ = repair
    root = Path(rec['workspace']).parent / 'controller'
    (root / 'crew').mkdir(parents=True)
    # No pane identity can never invoke task publication.
    monkeypatch.setattr(cli, '_spawn_inside', lambda *a, **k: None)
    monkeypatch.setattr(cli, '_spawn_actor', lambda **k: None)
    monkeypatch.setattr(pub, 'publish', lambda *a, **k: pytest.fail('unbound publication'))
    assert _st(root, '--publish', '--head', head) == cli.REFUSED


def test_task_policy_grants_publish_only_for_its_existing_pr():
    rec = dict(name='eph-task-abc123', job='task', harness='codex', repo='o/n', pr=7, item='it-1')
    rule = '"--publish"'
    assert rule in eph.codex_job_rules(rec, unattended=False)
    assert rule not in eph.codex_job_rules(dict(rec, pr=None), unattended=False)
    assert rule not in eph.codex_job_rules(dict(rec, job='triage'), unattended=False)
    assert eph.codex_job_rules(dict(rec, uid_binding={'uid': 1}), unattended=False) is None


def test_lost_readback_is_unknown_after_one_push(repair):
    rec, head, info, run, calls, remote, _ = repair
    def unreadable(*args):
        if args[2] == 'ls-remote':
            return subprocess.CompletedProcess(args, 1, '', 'unavailable')
        return run(*args)
    with pytest.raises(eph.Refused, match='read-back UNKNOWN'):
        pub.publish(rec, head, gh=lambda _: info, git=unreadable)
    assert len([c for c in calls if c[2] == 'push']) == 1
    assert git('--git-dir', remote, 'rev-parse', 'refs/heads/feature/fix').stdout.strip() == head


@pytest.mark.parametrize('override', [dict(job='merge'), dict(state=eph.DONE), dict(uid_binding={'uid': 1})])
def test_other_jobs_or_protected_uid_cannot_publish(repair, override):
    rec, head, info, run, calls, remote, _ = repair
    with pytest.raises(eph.Refused, match='live attended task'):
        pub.publish(dict(rec, **override), head, gh=lambda _: pytest.fail('no forge read'),
                    git=lambda *a: pytest.fail('no Git action'))


def test_publish_cli_dispatches_only_its_bound_task(repair, monkeypatch):
    from shantytown import cli
    from test_ephemeral import _st
    rec, head, info, run, calls, remote, _ = repair
    root = Path(rec['workspace']).parent / 'controller'
    (root / 'crew').mkdir(parents=True)
    monkeypatch.setenv('SHANTY_AGENT', rec['name'])
    monkeypatch.setattr(cli, '_spawn_inside', lambda *a, **k: rec['name'])
    monkeypatch.setattr(cli, '_spawn_actor', lambda **k: rec['name'])
    monkeypatch.setattr(eph, 'read', lambda *a: rec)
    published = []
    monkeypatch.setattr(pub, 'publish', lambda record, sha, **k: published.append((record, sha)) or {'verified': True})
    assert _st(root, '--publish', '--head', head) == cli.OK
    assert published == [(rec, head)]


def test_provisioned_kit_does_not_strand_a_clean_repair(repair):
    rec, head, info, run, calls, remote, _ = repair
    kit = Path(rec['workspace']) / '.agents'
    kit.mkdir()
    (kit / 'runtime.json').write_text('{}')
    assert pub.publish(rec, head, gh=lambda _: info, git=run)['verified'] is True
