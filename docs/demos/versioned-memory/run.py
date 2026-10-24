"""Same synthetic CLI inspection on base/head. No network or native activation."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[3]
BASE = '708b0348d7ff5dbe140397b95f0b339a4c23a2b4'


def main():
    head = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    with tempfile.TemporaryDirectory(prefix='memory-source-demo-') as folder:
        scratch = Path(folder)
        native = scratch / 'synthetic-native'
        native.mkdir()
        (native / 'MEMORY.md').write_bytes(b'# Synthetic index\r\n[Topic](topic.md)\r\n')
        (native / 'topic.md').write_bytes('Synthetic topic λ\n'.encode())
        original = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in native.iterdir()}
        base = scratch / 'base'
        base.mkdir()
        data = subprocess.check_output(['git', '-C', str(ROOT), 'archive', BASE, 'shantytown'])
        # Repository bytes only; refuse links or traversal rather than relaxing
        # extraction for a demonstration. No worktree or shared index is created.
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            for member in archive.getmembers():
                parts = PurePosixPath(member.name).parts
                if (not parts or parts[0] != 'shantytown' or '..' in parts
                        or not (member.isfile() or member.isdir())):
                    raise RuntimeError('unsafe source archive')
                target = base.joinpath(*parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
        print('Synthetic source-only demo; no credential, network or native selection.')
        print('Probe: python -m shantytown.cli --root FIXTURE agent memory alpha inspect --directory SYNTHETIC_NATIVE')
        for label, revision, source, expected in [('base', BASE, base, 2), ('head', head, ROOT, 0)]:
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(('SHANTY_', 'ST_', 'QUIPU_'))}
            env['PYTHONPATH'] = str(source)
            result = subprocess.run([sys.executable, '-m', 'shantytown.cli', '--root',
                str(scratch / 'deployment'), 'agent', 'memory', 'alpha', 'inspect',
                '--directory', str(native)], env=env, cwd=scratch,
                capture_output=True, text=True, timeout=5)
            print(f'{label} {revision} exit={result.returncode}')
            assert result.returncode == expected, result.stderr
            if label == 'base':
                assert "invalid choice: 'memory'" in result.stderr
                print('  memory command unavailable (actual parser refusal)')
            else:
                value = json.loads(result.stdout)
                assert len(value['files']) == 2 and value['native_selection'] == 'UNCHANGED'
                print(json.dumps(value, indent=2, sort_keys=True))
        assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in native.iterdir()} == original
        print('Positive target coverage: 2/2 files. Original bytes and mtimes unchanged.')
        print('Native Claude startup/write/read, Quipu round-trip and deployment: NOT exercised.')


if __name__ == '__main__':
    main()
