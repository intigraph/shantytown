#!/usr/bin/env python3
"""Compare the real hook with identical context controls, without a network push."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
GUARD = ROOT / 'scripts/pre-push-scrub-guard.sh'
BASE = '39f4bf93a956c57a1b7a7ec7f42be3a46cb4a076'
HEAD = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
print(f'TARGET=source-fixture BASE={BASE} HEAD={HEAD}', flush=True)
old = subprocess.check_output(['git', 'show', f'{BASE}:scripts/pre-push-scrub-guard.sh'], cwd=ROOT, text=True)
new = GUARD.read_text()
# Apply the SAME new real-hook controls to the original matcher. Only the
# disposable copy receives these controls; repository and installed files stay put.
start = new.index('  # Exercise version/address contexts')
end = new.index('  [ "$fail" -eq 0 ]', start)
old_start = old.index('  # Exercise the exact artifact exception')
old_end = old.index('  [ "$fail" -eq 0 ]', old_start)
old = old[:old_start] + new[start:end] + old[old_end:]
with tempfile.TemporaryDirectory(prefix='version-context-demo-') as directory:
    root = Path(directory)
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_') and key != 'BASH_ENV'}
    env.update(HOME=str(root), SCRUB_PATTERNS_FILE=str(root / 'absent-config'),
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    for label, source in [('BEFORE', old), ('AFTER', new)]:
        script = root / f'{label.lower()}.sh'
        script.write_text(source)
        script.chmod(0o700)
        started = time.monotonic()
        result = subprocess.run(['bash', str(script), '--selftest'], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=90)
        lines = result.stdout.splitlines()
        failed_lines = [line for line in lines if line.startswith('FAIL version/address context:')]
        failed = [line.split(' (rc=', 1)[0] for line in lines if line.startswith('FAIL version/address context:')]
        passed = [line for line in lines if line.startswith('ok   version/address context:')]
        print(f'{label} exit={result.returncode} context_passes={len(passed)} '
              f'elapsed={time.monotonic()-started:.3f}s source_sha256={hashlib.sha256(source.encode()).hexdigest()}', flush=True)
        if label == 'BEFORE':
            assert result.returncode == 1 and failed == ['FAIL version/address context: other_repo'], result.stdout
            print('BEFORE ' + failed_lines[0], flush=True)
        else:
            assert result.returncode == 0 and len(passed) == 36, result.stdout
            print('AFTER: version cases pass; private addresses, authorities, adjacent leaks, '
                  'ambiguous contexts, parser failure and commit-message leaks still refuse', flush=True)
            for arm in ['other_repo', 'address_path', 'private_host', 'query', 'named_host']:
                line = next(line for line in passed if line.startswith(f'ok   version/address context: {arm} '))
                print('AFTER ' + line, flush=True)
            assert 'ok   chained refusal refuses the push' in result.stdout
            print('AFTER: chained refusal retained', flush=True)
