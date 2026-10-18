"""Render identical synthetic configuration on retained base and candidate."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

REPO = Path(__file__).resolve().parents[3]
REVISIONS = [('base', '708b0348d7ff5dbe140397b95f0b339a4c23a2b4'),
             ('candidate', 'b6b299ed146f1b58aa3f45281aa997aaad76bce9')]
PROBE = '''
import json
from pathlib import Path
from shantytown.harness import ClaudeHarness
root = Path('fixture')
root.mkdir()
root.joinpath('shantytown.toml').write_text('[env]\\nQUIPU_SERVER="http://graph.example.invalid"\\nDESIRE_PATH_METRICS_PUSHGATEWAY="http://metrics@example.invalid"\\nDESIRE_PATH_METRICS_PASSWORD_FILE="/fixture/not-read/password"\\n')
h = ClaudeHarness()
env = json.loads(h.render(h.settings('worker', root=root), root=root))['env']
keys = ('DESIRE_PATH_METRICS_PUSHGATEWAY', 'DESIRE_PATH_METRICS_PASSWORD_FILE')
print(json.dumps({'graph_control': env.get('QUIPU_SERVER') == 'http://graph.example.invalid', 'metrics_pair_present': all(k in env for k in keys)}, sort_keys=True))
'''
for label, rev in REVISIONS:
    with tempfile.TemporaryDirectory(prefix='metrics-demo-') as tmp:
        target = Path(tmp)
        archive = subprocess.check_output(['git', 'archive', rev, 'shantytown'], cwd=REPO)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
            # Git archive contains trusted committed source only; prohibit links.
            members = tf.getmembers()
            assert all(m.isfile() or m.isdir() for m in members)
            assert all(not m.name.startswith('/') and '..' not in Path(m.name).parts for m in members)
            tf.extractall(target, members=members)
        (target/'home').mkdir()
        env = {'PATH': os.defpath, 'HOME': str(target/'home'), 'PYTHONPATH': str(target),
               'PYTHONDONTWRITEBYTECODE': '1'}
        print(f'{label} {rev}: actual Claude renderer; identical synthetic input', flush=True)
        result = subprocess.check_output([sys.executable, '-c', PROBE], cwd=target, env=env, text=True)
        print(result.strip(), flush=True)
        measured = json.loads(result)
        assert measured['graph_control'] is True
        assert measured['metrics_pair_present'] == (label == 'candidate')
print('PASS: same positive control; omitted pair -> carried pair. Source fixtures only; no producer invoked.')
