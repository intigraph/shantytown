"""Run identical isolated close fixtures on the baseline and committed source."""
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

root = Path(__file__).resolve().parents[3]
baseline = '834b8811c4ceafe8f58d425f384ee902590db369'
candidate = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
driver = Path(__file__).with_name('demo.py')
with tempfile.TemporaryDirectory() as directory:
    private = Path(directory)
    print('CONTROLLED FIXTURE: real close CLI; simulated blocker refusal; no live tracker writes', flush=True)
    for label, ref, expected in [('BEFORE', baseline, 'legacy'), ('AFTER', candidate, 'fixed')]:
        checkout = private / label
        checkout.mkdir()
        archive = subprocess.check_output(['git', '-C', str(root), 'archive', ref])
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(checkout, filter='data')
        home = private / (label + '-home')
        home.mkdir()
        env = {'PATH': os.environ['PATH'], 'HOME': str(home), 'PYTHONNOUSERSITE': '1'}
        for key in ('XDG_STATE_HOME', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME'):
            env[key] = str(home / key)
        print(label + ' ' + ref, flush=True)
        subprocess.run([sys.executable, '-B', str(driver), '--source', str(checkout),
                        '--expect', expected], cwd=checkout, env=env, check=True)
