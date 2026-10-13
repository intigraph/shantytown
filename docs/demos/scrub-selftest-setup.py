#!/usr/bin/env python3
"""Show clone-failure containment using only disposable local Git repositories."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('selftest_probe', root / 'tests/test_scrub_guard_selftest.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
with tempfile.TemporaryDirectory(prefix='scrub-demo-') as temporary:
    before = Path(temporary) / 'before.sh'
    before.write_bytes(subprocess.check_output([
        'git', '-C', str(root), 'show',
        'f59ada8530d82f4537f9bc82db113a38885e87dc:scripts/pre-push-scrub-guard.sh']))
    before.chmod(0o755)
    candidate = root / 'scripts/pre-push-scrub-guard.sh'
    for revision, guard in [('before', before), ('after', candidate)]:
        for fault in ['clone', 'none']:
            result = probe.probe(guard, fault)
            print(json.dumps({'revision': revision, 'fault': fault,
                              'fault_observed': result['fault_seen'], 'exit': result['exit'],
                              'caller_changed_paths': len(result['caller_changes']),
                              'positive_controls': result['positive_controls']}))
