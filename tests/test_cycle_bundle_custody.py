"""Bundle custody binds actual Git evidence to two item comment authors."""
import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest
from shantytown import cycle
from shantytown import cycle_custody as custody


def git(tree, *args):
    return subprocess.check_output(['git', '-C', str(tree), *args], stderr=subprocess.PIPE).decode().strip()


@pytest.fixture
def saved(tmp_path):
    tree = tmp_path / 'work'
    tree.mkdir()
    git(tree, 'init', '-q')
    git(tree, 'config', 'user.name', 'Fixture')
    git(tree, 'config', 'user.email', 'fixture@example.test')
    (tree / 'file').write_text('saved work')
    git(tree, 'add', 'file')
    git(tree, 'commit', '-qm', 'saved')
    git(tree, 'branch', '-M', 'topic')
    bundle = tmp_path / 'work.bundle'
    git(tree, 'bundle', 'create', str(bundle), 'refs/heads/topic')
    receipt = dict(agent='worker', tree=str(tree), ref='refs/heads/topic',
                   head=git(tree, 'rev-parse', 'HEAD'), bundle=str(bundle),
                   sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(), reason='archived')
    cards = {'root': SimpleNamespace(role='administrator', reports_to=''),
             'peer': SimpleNamespace(role='worker', reports_to='root')}
    return tree, bundle, receipt, cards


def comments(receipt):
    digest = custody.receipt_digest(receipt)
    return [{'author': 'peer', 'text': 'cycle-bundle-verified-v1 ' + digest},
            {'author': 'root', 'text': 'cycle-bundle-accepted-v1 ' + json.dumps(receipt)}]


def verify(saved, receipt=None, rows=None):
    tree, _, original, cards = saved
    receipt = original if receipt is None else receipt
    approved = custody.accepted_receipts(rows if rows is not None else comments(receipt),
                                         cards.get, 'worker', 'item-123')
    return custody.verify_tree(tree, 'worker', approved)


def test_exact_full_bundle_is_custody(saved):
    assert verify(saved)


def test_root_can_independently_verify_another_agents_work(saved):
    rows = comments(saved[2])
    rows[0]['author'] = 'root'
    assert verify(saved, rows=rows)


@pytest.mark.parametrize('failure', ['missing', 'digest', 'head', 'ref', 'agent', 'root', 'self', 'thin'])
def test_incorrect_or_unaccepted_custody_refuses(saved, failure):
    tree, bundle, receipt, cards = saved
    rows = None
    if failure == 'missing':
        bundle.unlink()
    elif failure == 'digest':
        receipt['sha256'] = '0' * 64
    elif failure == 'head':
        receipt['head'] = '0' * 40
    elif failure == 'ref':
        receipt['ref'] = 'refs/heads/other'
    elif failure == 'agent':
        receipt['agent'] = 'someone-else'
    elif failure == 'root':
        cards['root'].role = 'worker'
    elif failure == 'self':
        rows = comments(receipt)
        rows[0]['author'] = 'worker'
    elif failure == 'thin':
        parent = receipt['head']
        (tree / 'file').write_text('new work')
        git(tree, 'commit', '-qam', 'next')
        git(tree, 'bundle', 'create', str(bundle), 'refs/heads/topic', '^' + parent)
        receipt['head'] = git(tree, 'rev-parse', 'HEAD')
        receipt['sha256'] = hashlib.sha256(bundle.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        verify(saved, rows=rows)


def test_advanced_head_refuses_old_receipt(saved):
    tree, _, _, _ = saved
    (tree / 'file').write_text('later')
    git(tree, 'commit', '-qam', 'later')
    with pytest.raises(ValueError):
        verify(saved)


def test_only_matching_clean_tree_is_cleared(saved):
    tree, _, receipt, cards = saved
    approved = custody.accepted_receipts(comments(receipt), cards.get, 'worker', 'item-123')
    look = lambda _: SimpleNamespace(dirty=False, unpushed=1, error=None)
    gate = lambda t: custody.verify_tree(t, 'worker', approved)
    v = cycle.assess('worker', [tree], 'saved checkpoint', look,
                     reachable=lambda _: None, custody=gate)
    assert v.ok and 'bundle custody' in v.render()
    dirty = lambda _: SimpleNamespace(dirty=True, unpushed=1, error=None)
    assert not cycle.assess('worker', [tree], 'saved', dirty, custody=gate).ok
    v = cycle.assess('worker', [tree, tree.parent / 'unrelated'], 'saved', look,
                     reachable=lambda _: None, custody=gate)
    assert not v.ok and len(v.risks) == 1


def test_custody_items_survive_self_request(tmp_path, monkeypatch):
    from argparse import Namespace
    from shantytown import cli
    requests = cycle.Requests(tmp_path)
    requests.request('worker', 'saved', bundle_custody_items=['item-123'])
    seen = []
    monkeypatch.setattr(cli, '_cmd_cycle', lambda a: seen.append(a) or 0)
    cli._serve_cycle_request(Namespace(root=tmp_path), 'worker', requests.pending()['worker'])
    assert seen[0].bundle_custody_item == ['item-123']
    requests.request('worker', 'next')
    assert not requests.pending()['worker'].get('bundle_custody_items')


def test_bundle_without_current_head_refuses(saved):
    tree, bundle, receipt, _ = saved
    old = receipt['head']
    git(tree, 'branch', 'old', old)
    (tree / 'file').write_text('current')
    git(tree, 'commit', '-qam', 'current')
    receipt['head'] = git(tree, 'rev-parse', 'HEAD')
    git(tree, 'bundle', 'create', str(bundle), 'refs/heads/old')
    receipt['sha256'] = hashlib.sha256(bundle.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='absent from bundle'):
        verify(saved)


def test_unverified_payload_and_symlink_refuse(saved):
    with pytest.raises(ValueError, match='independent'):
        verify(saved, rows=comments(saved[2])[1:])
    tree, bundle, receipt, _ = saved
    link = bundle.with_name('alias.bundle')
    link.symlink_to(bundle)
    receipt['bundle'] = str(link)
    with pytest.raises(ValueError, match='symlinks'):
        verify(saved)


def test_item_reader_unknown_is_not_custody(monkeypatch):
    from argparse import Namespace
    from shantytown import cli, br
    monkeypatch.setattr(cli, '_backend', lambda *a: 'br')
    monkeypatch.setattr(cli, '_tracker', lambda *a: object())
    monkeypatch.setattr(cli, '_registry', lambda *a: SimpleNamespace(get=lambda _: None))
    def unavailable(*_):
        raise RuntimeError('fixture offline')
    monkeypatch.setattr(br, 'comments', unavailable)
    with pytest.raises(ValueError, match='unavailable'):
        cli._cycle_bundle_custody(Namespace(bundle_custody_item=['item-123']), 'worker')


def test_native_parser_and_item_reader_bind_comment_authors(saved, monkeypatch):
    from shantytown import cli, br
    tree, _, receipt, cards = saved
    args = cli.build_parser().parse_args(['agent', 'cycle', 'worker',
                                         '--bundle-custody-item', 'item-123'])
    monkeypatch.setattr(cli, '_backend', lambda *a: 'br')
    monkeypatch.setattr(cli, '_tracker', lambda *a: object())
    monkeypatch.setattr(cli, '_registry', lambda *a: SimpleNamespace(get=cards.get))
    seen = []
    def read(_, item):
        seen.append(item)
        return comments(receipt)
    monkeypatch.setattr(br, 'comments', read)
    assert cli._cycle_bundle_custody(args, 'worker')(tree)
    assert seen == ['item-123']
