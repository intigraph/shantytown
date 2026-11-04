"""Offline before/after PR preflight; synthetic Git and API only, no live writer."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shantytown import pr_preflight as current

BASE = '4e6500e808c49422987311f221d00cc54339f9e8'
REPO = 'example/project'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)


def probe(module, mode):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        git(root, 'init', '-q', '-b', 'main')
        git(root, 'config', 'user.email', 'fixture@example.invalid')
        git(root, 'config', 'user.name', 'Fixture')
        (root / 'source').write_text('base\n')
        git(root, 'add', 'source')
        git(root, 'commit', '-qm', 'base')
        base = git(root, 'rev-parse', 'HEAD').decode().strip()
        git(root, 'checkout', '-qb', 'feature')
        (root / 'source').write_text('candidate\n')
        git(root, 'commit', '-qam', 'candidate')
        head = git(root, 'rev-parse', 'HEAD').decode().strip()
        git(root, 'remote', 'add', 'origin', 'https://github.com/example/project.git')
        scratch = root / ('.task-notes' if mode == 'task notes' else '.work')
        if mode == 'symlink root':
            scratch.symlink_to(root / 'unused', target_is_directory=True)
        else:
            scratch.mkdir()
            note = scratch / 'synthetic note'
            note.write_bytes(b'inert fixture content')
            note.chmod(0o600)
        if mode == 'tracked dirty':
            (root / 'source').write_text('uncommitted\n')
        status = git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
        writes = []
        def api(path, body=None):
            if body is not None:
                writes.append(body)
                return {'number': 1, 'html_url': f'https://github.com/{REPO}/pull/1',
                        'head': {'sha': head}, 'base': {'sha': base}}
            if path == f'repos/{REPO}':
                return {'id': 123, 'full_name': REPO}
            if '/commits/' in path:
                return {'sha': head if path.endswith('/feature') else base}
            return []
        try:
            result = module.run(root, REPO, 'main', 'project-scratch', 'Fixture change',
                                'Fixture', [], create=True, api=api)
            assert result['candidate']['files'] == ['source']
            assert len(writes) == 1
            assert 'inert fixture' not in json.dumps(result) + json.dumps(writes)
            answer = 'ADMIT'
        except module.Refused:
            assert not writes
            answer = 'REFUSE'
        assert git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all') == status
        if mode != 'symlink root':
            assert note.read_bytes() == b'inert fixture content' and note.stat().st_mode & 0o777 == 0o600
        return answer


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'baseline.py'
        path.write_bytes(git(ROOT, 'show', BASE + ':shantytown/pr_preflight.py'))
        spec = importlib.util.spec_from_file_location('shantytown._preflight_baseline', path)
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)
        print('Offline real Git/API fixtures; no network or live PR creation.')
        print('Baseline:', BASE)
        for mode in ('work notes', 'task notes', 'tracked dirty', 'symlink root'):
            before, after = probe(baseline, mode), probe(current, mode)
            assert before == 'REFUSE'
            assert after == ('ADMIT' if mode in ('work notes', 'task notes') else 'REFUSE')
            print(f'{mode}: baseline={before} candidate={after}; private state preserved')


if __name__ == '__main__':
    main()
