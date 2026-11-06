#!/usr/bin/env python3
"""Demonstrate capture/scrub against identical private relocated fixtures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE = '2bd929f8'


def run(script, env, *args):
    result = subprocess.run(['bash', str(script), '--agent', 'tester', *args],
                            env=env, capture_output=True, text=True, check=True)
    return result.stdout


def relocate(path, cold):
    target = cold / path.parent.name / path.name
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.replace(target)
    target.chmod(0o600)
    path.symlink_to(target)
    return target


def demonstrate(label, scripts, root):
    root.mkdir()
    raw, out, codex, claude = [root / name for name in ('raw', 'out', 'codex', 'claude')]
    for path in (raw / 'tester', out, codex / 'tester/sessions', claude):
        path.mkdir(parents=True)
    env = dict(os.environ, ST_HISTORY_DIR=str(raw), ST_HISTORY_SCRUBBED_DIR=str(out),
               ST_CODEX_ROOT=str(codex), ST_CLAUDE_ROOT=str(claude))
    src = codex / 'tester/sessions/rollout-demo.jsonl'
    src.write_text(json.dumps({'text': 'dialogue ' * 40}) + '\n')
    dst = raw / 'tester' / src.name
    dst.write_bytes(src.read_bytes())
    target = relocate(dst, root / 'cold-raw')
    inode = target.stat().st_ino
    result = run(scripts / 'st-history-capture.sh', env)
    skipped = 'captured=0 skipped_unchanged=1' in result
    unchanged = dst.is_symlink() and target.stat().st_ino == inode
    print(f'{label} unchanged capture: skipped={skipped}, citation/target preserved={unchanged}')
    # Restore the same citation for the growth probe, independent of skip behavior.
    if not dst.is_symlink():
        dst.unlink()
        dst.symlink_to(target)
    src.write_text(src.read_text() + json.dumps({'text': 'ghp_' + 'A' * 22}) + '\n')
    run(scripts / 'st-history-capture.sh', env)
    growing = dst.is_symlink() and target.read_bytes() == src.read_bytes()
    print(f'{label} growing capture: citation preserved + archive current={growing}')
    run(scripts / 'st-history-scrub.sh', env)
    derivative = out / 'tester' / src.name
    scrubbed = relocate(derivative, root / 'cold-scrubbed')
    before = dst.read_bytes()
    run(scripts / 'st-history-scrub.sh', env, '--full')
    redacted = b'ghp_' not in scrubbed.read_bytes() and b'REDACTED' in scrubbed.read_bytes()
    preserved = derivative.is_symlink()
    print(f'{label} full scrub: citation preserved={preserved}, redacted={redacted}, raw unchanged={dst.read_bytes() == before}')
    if label == 'HEAD':
        assert skipped and unchanged and growing and preserved and redacted


with tempfile.TemporaryDirectory(prefix='history-relocation-demo-') as temporary:
    root = Path(temporary)
    base = root / 'base-scripts'
    base.mkdir()
    for filename in ('st-history-capture.sh', 'st-history-scrub.sh'):
        result = subprocess.run(['git', 'show', f'{BASE}:scripts/{filename}'],
                                cwd=ROOT, capture_output=True, check=True)
        (base / filename).write_bytes(result.stdout)
    print(f'Synthetic fixture; base={BASE}; candidate=working tree; no installed-service claim.')
    demonstrate('BASE', base, root / 'before')
    demonstrate('HEAD', ROOT / 'scripts', root / 'after')
