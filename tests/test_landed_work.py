"""Real Git loss/cleanup regressions; the forge response is an explicit fixture."""
import subprocess
from pathlib import Path

import pytest

from shantytown import landed
from shantytown.cycle import assess
from shantytown.workspace import _git, tree_staleness


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def merged(tmp_path, monkeypatch):
    origin, seed, wt = [tmp_path / name for name in ('origin.git', 'seed', 'wt')]
    origin.mkdir(); git(origin, 'init', '--bare', '-b', 'main')
    git(tmp_path, 'clone', str(origin), str(seed))
    git(seed, 'config', 'user.name', 'Fixture'); git(seed, 'config', 'user.email', 'fixture@example.org')
    (seed / 'base').write_text('base'); git(seed, 'add', '.'); git(seed, 'commit', '-m', 'base')
    base = git(seed, 'rev-parse', 'HEAD'); git(seed, 'push', 'origin', 'main')
    git(tmp_path, 'clone', str(origin), str(wt))
    git(wt, 'config', 'user.name', 'Fixture'); git(wt, 'config', 'user.email', 'fixture@example.org')
    git(wt, 'checkout', '-b', 'feature')
    for n in range(2):
        (wt / f'feature{n}').write_text(str(n)); git(wt, 'add', '.'); git(wt, 'commit', '-m', f'feature{n}')
    head = git(wt, 'rev-parse', 'HEAD'); git(wt, 'push', '-u', 'origin', 'feature')
    git(seed, 'fetch', 'origin'); git(seed, 'merge', '--squash', 'origin/feature')
    git(seed, 'commit', '-m', 'squash feature'); merge = git(seed, 'rev-parse', 'HEAD')
    git(seed, 'push', 'origin', 'main'); git(seed, 'push', 'origin', '--delete', 'feature')
    real_identity = landed.forge_identity
    monkeypatch.setattr(landed, 'forge_identity', lambda url: ('https://forge.example', 'forge.example', 'owner/repo') if url == str(origin) else real_identity(url))
    rows = [{'number': 7, 'state': 'closed', 'merged_at': '2026-01-01T00:00:00Z',
             'base': {'repo': {'full_name': 'owner/repo'}}, 'head': {'sha': head}, 'merge_commit_sha': merge}]
    calls = []
    def read(url):
        calls.append(url)
        return rows
    monkeypatch.setattr(landed, 'read_merged_prs', read)
    return wt, rows, calls, base, head


def cycle(wt):
    return assess('fixture', [wt], 'fixture checkpoint', lambda tree: tree_staleness(tree, fetch=True, tracked_only=True), reachable=lambda _: True)


def test_deleted_squash_branch_clears_only_landed_commits_and_reports_proof(merged):
    wt, _, calls, _, _ = merged
    value = cycle(wt)
    assert value.ok and 'merged PR #7' in value.render()
    assert len(calls) == 1
    (wt / 'new').write_text('genuinely unpublished'); git(wt, 'add', '.'); git(wt, 'commit', '-m', 'new')
    value = cycle(wt)
    assert not value.ok and value.risks[0].unpushed == 1
    assert 'merged PR #7' in value.render()
    assert len(calls) == 1, 'positive merged history is cached across worktrees/readings'


@pytest.mark.parametrize('bad', ['open', 'closed-unmerged', 'wrong-repo', 'missing-head', 'unlanded-merge'])
def test_unproved_forge_results_never_clear_commits(merged, bad):
    wt, rows, _, base, head = merged
    if bad == 'open': rows[0]['state'] = 'open'
    if bad == 'closed-unmerged': rows[0]['merged_at'] = None
    if bad == 'wrong-repo': rows[0]['base']['repo']['full_name'] = 'other/repo'
    if bad == 'missing-head': rows[0]['head'] = None
    if bad == 'unlanded-merge': rows[0]['merge_commit_sha'] = head
    assert not cycle(wt).ok
    assert tree_staleness(wt).unpushed == 2


def test_api_failure_and_corrupt_cache_preserve_unknown_work(merged, monkeypatch):
    wt, _, _, _, _ = merged
    def fail(_): raise OSError('offline')
    monkeypatch.setattr(landed, 'read_merged_prs', fail)
    assert not cycle(wt).ok
    proof = landed.Proofs(wt, 'origin', _git)
    proof.path.parent.mkdir(exist_ok=True)
    proof.path.write_text('["malformed"]')
    assert tree_staleness(wt).unpushed == 2


def test_patch_equivalence_without_a_forge_retains_new_work(tmp_path):
    seed, wt = tmp_path / 'seed', tmp_path / 'wt'
    seed.mkdir(); git(seed, 'init', '-b', 'main')
    git(seed, 'config', 'user.name', 'Fixture'); git(seed, 'config', 'user.email', 'fixture@example.org')
    (seed / 'base').write_text('base'); git(seed, 'add', '.'); git(seed, 'commit', '-m', 'base')
    git(tmp_path, 'clone', str(seed), str(wt))
    git(wt, 'config', 'user.name', 'Fixture'); git(wt, 'config', 'user.email', 'fixture@example.org')
    git(wt, 'checkout', '-b', 'feature')
    (wt / 'feature').write_text('patch'); git(wt, 'add', '.'); git(wt, 'commit', '-m', 'feature')
    (seed / 'unrelated').write_text('advance'); git(seed, 'add', '.'); git(seed, 'commit', '-m', 'advance')
    git(seed, 'fetch', str(wt), 'feature'); git(seed, 'cherry-pick', 'FETCH_HEAD')
    result = tree_staleness(wt, fetch=True, tracked_only=True)
    assert result.unpushed == 0 and 'patch-equivalent' in result.render()
    (wt / 'unpublished').write_text('keep'); git(wt, 'add', '.'); git(wt, 'commit', '-m', 'unpublished')
    assert tree_staleness(wt, fetch=True, tracked_only=True).unpushed == 1


def test_safe_refresh_detaches_and_prunes_only_landed_gone_unoccupied_refs(merged, tmp_path):
    wt, _, _, base, head = merged
    assert cycle(wt).ok
    git(wt, 'branch', 'occupied', head)
    git(wt, 'config', 'branch.occupied.remote', 'origin'); git(wt, 'config', 'branch.occupied.merge', 'refs/heads/deleted')
    git(wt, 'worktree', 'add', str(tmp_path / 'other'), 'occupied')
    git(wt, 'checkout', '-b', 'not-landed')
    (wt / 'private-work').write_text('keep'); git(wt, 'add', '.'); git(wt, 'commit', '-m', 'private-work')
    unknown = git(wt, 'rev-parse', 'HEAD')
    git(wt, 'config', 'branch.not-landed.remote', 'origin'); git(wt, 'config', 'branch.not-landed.merge', 'refs/heads/deleted')
    git(wt, 'checkout', 'feature')
    message = landed.retire_and_prune(wt, ['origin'], _git)
    assert 'detached' in message and 'pruned 1' in message
    assert _git(wt, 'symbolic-ref', '--quiet', 'HEAD')[0] != 0
    assert git(wt, 'rev-parse', 'HEAD') == git(wt, 'rev-parse', 'origin/main')
    assert _git(wt, 'show-ref', '--verify', 'refs/heads/feature')[0] != 0
    assert git(wt, 'rev-parse', 'occupied') == head
    assert git(wt, 'rev-parse', 'not-landed') == unknown
    assert git(wt, 'rev-parse', f'refs/st/landed-retained/{head}') == head


@pytest.mark.parametrize('dirt', ['tracked', 'untracked', 'unlanded'])
def test_refresh_preserves_any_local_work(merged, dirt):
    wt, _, _, _, head = merged
    assert cycle(wt).ok
    if dirt == 'tracked': (wt / 'base').write_text('unsaved')
    else: (wt / 'new').write_text('keep')
    if dirt == 'unlanded': git(wt, 'add', '.'); git(wt, 'commit', '-m', 'unlanded')
    current = git(wt, 'rev-parse', 'HEAD')
    assert landed.retire_and_prune(wt, ['origin'], _git) is None
    assert git(wt, 'rev-parse', 'HEAD') == current
    assert git(wt, 'symbolic-ref', '--short', 'HEAD') == 'feature'


def test_unknown_remote_or_mirror_does_not_supply_merged_proof(merged):
    wt, rows, calls, _, _ = merged
    git(wt, 'config', 'remote.origin.st-push-role', 'mirror')
    # No trusted publication peer: the cycle measurement must refuse.
    assert tree_staleness(wt, fetch=True, tracked_only=True).error
    assert not calls


def test_forge_url_parsing_never_accepts_embedded_http_credentials():
    assert landed.forge_identity('https://secret@forge.example/a/b.git') is None
    assert landed.forge_identity('https://user:secret@forge.example/a/b.git') is None
    assert landed.forge_identity('git@github.com:owner/repo.git')[2] == 'owner/repo'
    assert landed.forge_identity('/local/path') is None


def test_changed_branch_tip_cannot_inherit_old_landing_proof(merged):
    wt, _, _, _, head = merged
    assert cycle(wt).ok
    # A different commit is retained even if a concurrent writer changes the ref
    # after it was classified. Only the original OID may be deleted.
    new = git(wt, 'commit-tree', git(wt, 'rev-parse', 'HEAD^{tree}'), '-p', head, '-m', 'concurrent unpublished metadata')
    def racing_run(repo, *args):
        if args[:3] == ('update-ref', '-d', 'refs/heads/feature'):
            git(wt, 'update-ref', 'refs/heads/feature', new, head)
        return _git(repo, *args)
    result = landed.retire_and_prune(wt, ['origin'], racing_run)
    assert 'pruned 0' in result
    assert git(wt, 'rev-parse', 'feature') == new


def test_newly_occupied_branch_is_rechecked_before_pruning(merged, tmp_path):
    wt, _, _, _, head = merged
    assert cycle(wt).ok
    checks = 0
    def racing_run(repo, *args):
        nonlocal checks
        if args == ('worktree', 'list', '--porcelain'):
            checks += 1
            if checks == 2:
                git(wt, 'worktree', 'add', str(tmp_path / 'new-owner'), 'feature')
        return _git(repo, *args)
    result = landed.retire_and_prune(wt, ['origin'], racing_run)
    assert 'pruned 0' in result
    assert git(wt, 'rev-parse', 'feature') == head
    assert git(tmp_path / 'new-owner', 'symbolic-ref', '--short', 'HEAD') == 'feature'


def test_merged_cleanup_runs_through_the_existing_refresh_boundary(merged):
    from shantytown.cli import _refresh_worktree
    wt, _, calls, _, _ = merged
    message = _refresh_worktree(wt)
    assert 'landed worktree' in message and 'detached' in message
    assert len(calls) == 1
    # A later scheduled safe refresh also works on the detached tree.
    assert 'detached' in _refresh_worktree(wt)


def test_cleanup_never_acts_after_failed_fetch(merged, monkeypatch):
    import shantytown.workspace as workspace
    from shantytown.cli import _refresh_worktree
    wt, _, _, _, head = merged
    monkeypatch.setattr(workspace, 'run_with_group_timeout', lambda *a, **k: subprocess.CompletedProcess(a, 1, '', 'offline'))
    assert 'fetch failed' in _refresh_worktree(wt, 'origin/main')
    # _git also uses the replaced runner, so use the independent fixture runner.
    assert git(wt, 'rev-parse', 'HEAD') == head


def test_github_reader_is_bounded_and_keeps_auth_out_of_arguments(monkeypatch):
    import json
    import shantytown.workspace as workspace
    calls = []
    def request(args, timeout, **kwargs):
        calls.append((args, timeout))
        return subprocess.CompletedProcess(args, 0, json.dumps([]), '')
    monkeypatch.setattr(workspace, 'run_with_group_timeout', request)
    assert landed.read_merged_prs('git@github.com:owner/repo.git') == []
    args, timeout = calls[0]
    assert args[:2] == ['gh', 'api'] and 'per_page=50' in args[2]
    assert timeout == 10 and len(args) == 3


@pytest.mark.parametrize('same_origin', [True, False])
def test_forgejo_credentials_are_origin_bound_and_redirects_disabled(monkeypatch, same_origin):
    import json
    captured = []
    monkeypatch.setenv('SHANTY_FORGEJO_URL', 'http://forge.example' if same_origin else 'http://other.example')
    monkeypatch.setenv('SHANTY_FORGEJO_TOKEN', 'fixture-only-token')
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            assert size == 4_000_001
            return json.dumps([]).encode()
    class Opener:
        def open(self, request, timeout):
            captured.append(request)
            assert timeout == 10
            return Response()
    def opener(handler):
        assert handler.redirect_request(None) is None
        return Opener()
    monkeypatch.setattr(landed.urllib.request, 'build_opener', opener)
    assert landed.read_merged_prs('git@forge.example:owner/repo.git') == []
    request = captured[0]
    assert request.get_header('Authorization') == ('token fixture-only-token' if same_origin else None)
    assert request.full_url.startswith('http://forge.example/' if same_origin else 'https://forge.example/')


def test_remote_head_cannot_redirect_cleanup_to_a_local_topic(merged):
    wt, _, _, _, _ = merged
    git(wt, 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/heads/feature')
    assert cycle(wt).ok
    assert landed.Proofs(wt, 'origin', _git).base == 'refs/remotes/origin/main'
    message = landed.retire_and_prune(wt, ['origin'], _git)
    assert 'detached at refs/remotes/origin/main' in message
    assert git(wt, 'rev-parse', 'HEAD') == git(wt, 'rev-parse', 'origin/main')


def test_fresh_topic_at_main_is_not_mistaken_for_landed_work(merged):
    wt, rows, _, _, _ = merged
    git(wt, 'fetch', '--prune', 'origin')
    git(wt, 'checkout', '-b', 'fresh-topic', 'origin/main')
    head = git(wt, 'rev-parse', 'HEAD')
    # Even a different merged PR whose head equals main is not this new topic.
    rows.append(dict(rows[0], number=8, head={'sha':head, 'ref':'different-topic'}))
    assert landed.retire_and_prune(wt, ['origin'], _git) is None
    assert git(wt, 'symbolic-ref', '--short', 'HEAD') == 'fresh-topic'


def test_default_push_refuses_detached_work_without_publishing_a_stale_ref(merged, monkeypatch, capsys):
    import shantytown.cli as cli
    from argparse import Namespace
    wt, _, _, _, _ = merged
    assert cycle(wt).ok
    assert landed.retire_and_prune(wt, ['origin'], _git)
    (wt / 'new').write_text('held work'); git(wt, 'add', '.'); git(wt, 'commit', '-m', 'held work')
    monkeypatch.setattr(cli, '_resolve_push_worktree', lambda *a: wt)
    def no_push(*a, **k): raise AssertionError('detached work must never contact push remotes')
    monkeypatch.setattr(cli, 'push_every_remote', no_push)
    args = Namespace(branch='feature', agent='fixture', repo=str(wt), source_branch=None)
    assert cli._cmd_push(args) == cli.REFUSED
    assert 'source branch cannot be verified' in capsys.readouterr().err


def test_explicitly_retained_branch_survives_pruning(merged):
    wt, _, _, _, head = merged
    assert cycle(wt).ok
    git(wt, 'config', 'branch.feature.st-keep', 'true')
    assert 'pruned 0' in landed.retire_and_prune(wt, ['origin'], _git)
    assert git(wt, 'rev-parse', 'feature') == head


def test_main_ref_advance_during_cleanup_keeps_original_topic(merged):
    wt, _, _, _, head = merged
    assert cycle(wt).ok
    original = git(wt, 'rev-parse', 'origin/main')
    advanced = git(wt, 'commit-tree', git(wt, 'rev-parse', 'origin/main^{tree}'), '-p', original, '-m', 'concurrent main advance')
    reads = 0
    def racing_run(repo, *args):
        nonlocal reads
        if len(args) == 2 and args[0] == 'rev-parse' and args[1].endswith('/main'):
            reads += 1
            if reads == 2:
                git(wt, 'update-ref', 'refs/remotes/origin/main', advanced, original)
        return _git(repo, *args)
    assert landed.retire_and_prune(wt, ['origin'], racing_run) is None
    assert git(wt, 'rev-parse', 'HEAD') == head
    assert git(wt, 'symbolic-ref', '--short', 'HEAD') == 'feature'


def test_pr_reachability_is_reused_across_branch_checks(merged):
    wt, _, _, base, head = merged
    assert cycle(wt).ok
    calls = []
    def counting_run(repo, *args):
        calls.append(args)
        return _git(repo, *args)
    proof = landed.Proofs(wt, 'origin', counting_run)
    candidates = git(wt, 'rev-list', f'{base}..{head}').splitlines()
    assert proof.clear(candidates)[0] == set(candidates)
    assert proof.clear(candidates)[0] == set(candidates)
    assert sum(args[:2] == ('rev-list', '--max-count=512') for args in calls) == 1


def test_confirmed_fast_forward_pr_can_retire_its_equal_tip_topic(merged):
    wt, rows, _, _, _ = merged
    git(wt, 'fetch', '--prune', 'origin')
    git(wt, 'checkout', '-b', 'fast-topic', 'origin/main')
    head = git(wt, 'rev-parse', 'HEAD')
    rows.append(dict(rows[0], number=8, head={'sha':head, 'ref':'fast-topic'}, merge_commit_sha=head))
    assert 'detached' in landed.retire_and_prune(wt, ['origin'], _git)
    assert _git(wt, 'symbolic-ref', '--quiet', 'HEAD')[0] != 0


def test_main_reference_cannot_be_shadowed_by_local_branch(merged):
    wt, _, _, _, head = merged
    git(wt, 'fetch', '--prune', 'origin')
    git(wt, 'symbolic-ref', '--delete', 'refs/remotes/origin/HEAD')
    trusted = git(wt, 'rev-parse', 'refs/remotes/origin/main')
    git(wt, 'branch', 'origin/main', head)
    proof = landed.Proofs(wt, 'origin', _git)
    assert proof.base_oid == trusted
    assert proof.base == 'refs/remotes/origin/main'
