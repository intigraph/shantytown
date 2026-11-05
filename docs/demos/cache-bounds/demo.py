"""Source-only, isolated before/after probe; no fleet state or model calls."""
import io
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shantytown import cycle_advice as after

BASE = 'df023d8438a96f4a39f78a5ccd3a70c102281e8d'
source = subprocess.check_output(['git', 'show', BASE + ':shantytown/cycle_advice.py'], text=True)
before = types.ModuleType('shantytown._cache_before')
before.__package__ = 'shantytown'
sys.modules[before.__name__] = before
exec(compile(source, '<before>', 'exec'), before.__dict__)


class Counted(io.BytesIO):
    consumed = 0
    def read(self, size=-1):
        value = super().read(size)
        self.consumed += len(value)
        return value


def measure(module):
    old = module.work_facts({'id': 'old', 'repo': 'repo-a', 'files': ['src/main.py']})
    other = module.work_facts({'id': 'new', 'repo': 'repo-b', 'files': ['src/main.py']})
    same = module.work_facts({'id': 'new', 'repo': 'repo-a', 'files': ['src/main.py']})
    reader = Counted(b'x' * (8 * 1024 * 1024) + b'\n')
    with patch.object(Path, 'open', return_value=reader):
        cache = module.read_cache('synthetic.jsonl')
    return {'different_repo_score': module.overlap(old, other)[0],
            'same_repo_control': module.overlap(old, same)[0],
            'physical_bytes_read': reader.consumed,
            'oversized_record_unknown': cache.last_at is None}


print('Target: source library; identical relative path in different explicit repos, 8MiB final record')
print('BEFORE ' + BASE + ' ' + json.dumps(measure(before), sort_keys=True))
print('AFTER ' + subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
      + ' ' + json.dumps(measure(after), sort_keys=True))
assert measure(before)['different_repo_score'] == .9
assert measure(after)['different_repo_score'] == .2
assert measure(after)['physical_bytes_read'] <= 2 * 1024 * 1024
print('PASS: different-repo collision removed; physical scan bounded; same-repo control retained')
