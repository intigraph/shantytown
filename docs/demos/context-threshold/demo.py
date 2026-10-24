"""Run from the repository root: python3 docs/demos/context-threshold/demo.py BASE_REF."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

PROBE = '''
import json, tempfile
from pathlib import Path
from shantytown.context_hint import emit
from shantytown.protocols import Agent
for used in (500, 750):
    with tempfile.TemporaryDirectory() as name:
        root = Path(name)
        (root / 'shantytown.toml').write_text('[session_budget]\\ncontext_window=1000\\n')
        transcript = root / 'session.jsonl'
        transcript.write_text(json.dumps(dict(message=dict(usage=dict(input_tokens=used)))))
        print(f'Input: {used}/1000 tokens; declared monitoring, default thresholds')
        emitted = emit(root, Agent('fixture', role='administrator'),
                       dict(session_id='fixture', transcript_path=str(transcript)))
        print('Hint emitted:', emitted)
'''

base = sys.argv[1]
repo = Path(__file__).resolve().parents[3]
env = {k: v for k, v in os.environ.items() if not k.startswith(('SHANTY_', 'ST_'))}
with tempfile.TemporaryDirectory() as name:
    archive = Path(name) / 'base.tar'
    with archive.open('wb') as output:
        subprocess.run(['git', 'archive', base], cwd=repo, stdout=output, check=True)
    base_dir = Path(name) / 'base'
    base_dir.mkdir()
    with tarfile.open(archive) as source:
        source.extractall(base_dir, filter='data')
    for label, path in [('BASE ' + base, base_dir), ('CANDIDATE', repo)]:
        print(label, flush=True)
        subprocess.run([sys.executable, '-c', PROBE], cwd=path,
                       env=dict(env, PYTHONPATH=str(path)), check=True)
