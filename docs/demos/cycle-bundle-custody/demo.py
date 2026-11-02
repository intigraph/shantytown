"""Synthetic policy comparison; never cycles a session or contacts a tracker."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types

from shantytown import cycle, cycle_custody

BASE = '09c1c6a70d298dbe8cf254777e9063040e489211'


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args],
                                   stderr=subprocess.PIPE).decode().strip()


def main():
    base = types.ModuleType('shantytown._cycle_base_demo')
    sys.modules[base.__name__] = base
    source = subprocess.check_output(['git', 'show', BASE + ':shantytown/cycle.py'])
    exec(compile(source, '<retained base cycle.py>', 'exec'), base.__dict__)
    with tempfile.TemporaryDirectory(prefix='cycle-custody-demo-') as tmp:
        tree = Path(tmp) / 'work'
        tree.mkdir()
        git(tree, 'init', '-q')
        git(tree, 'config', 'user.name', 'Fixture')
        git(tree, 'config', 'user.email', 'fixture@example.test')
        (tree / 'work.txt').write_text('retained work\n')
        git(tree, 'add', 'work.txt')
        git(tree, 'commit', '-qm', 'retained work')
        git(tree, 'branch', '-M', 'topic')
        bundle = Path(tmp) / 'saved.bundle'
        git(tree, 'bundle', 'create', str(bundle), 'refs/heads/topic')
        payload = dict(agent='worker', tree=str(tree), ref='refs/heads/topic',
                       head=git(tree, 'rev-parse', 'HEAD'), bundle=str(bundle),
                       sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(), reason='archived')
        cards = {'root': types.SimpleNamespace(role='administrator', reports_to=None)}
        comments = [dict(author='root', text=cycle_custody.VERIFIED + cycle_custody.receipt_digest(payload)),
                    dict(author='root', text=cycle_custody.ACCEPT + json.dumps(payload))]
        approved = cycle_custody.accepted_receipts(comments, cards.get, 'worker', 'fixture-item')
        probe = lambda _: types.SimpleNamespace(dirty=False, unpushed=1, error=None)
        old = base.assess('worker', [tree], 'saved checkpoint', probe, reachable=lambda _: None)
        new = cycle.assess('worker', [tree], 'saved checkpoint', probe, reachable=lambda _: None,
                           custody=lambda t: cycle_custody.verify_tree(t, 'worker', approved))
        assert not old.ok and new.ok
        print('target: synthetic local Git bundle + item/card fixture; no live cycle')
        print('base ' + BASE + ': REFUSED (clean unpushed work, no publication route)')
        print('candidate: ACCEPTED (same work, exact independently verified/root-accepted bundle)')
        approved[0]['sha256'] = '0' * 64
        bad = cycle.assess('worker', [tree], 'saved checkpoint', probe, reachable=lambda _: None,
                           custody=lambda t: cycle_custody.verify_tree(t, 'worker', approved))
        assert not bad.ok
        print('wrong SHA256: REFUSED')
        dirty = cycle.assess('worker', [tree], 'saved checkpoint',
                            lambda _: types.SimpleNamespace(dirty=True, unpushed=1, error=None))
        assert not dirty.ok
        print('dirty tracked work: REFUSED')


if __name__ == '__main__':
    main()
