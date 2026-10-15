"""Run the same modeled launch sequence on base and candidate source."""
from pathlib import Path
import os
import subprocess
import sys
import tarfile
import tempfile

root = Path(__file__).resolve().parents[4]
base = 'c90765e89ea116f5b2aab234e3794031412ba107'
probe = Path(__file__).with_name('probe.py')
with tempfile.TemporaryDirectory(prefix='admin-capacity-demo-') as temp:
    before = Path(temp) / 'base'
    before.mkdir()
    archive = Path(temp) / 'source.tar'
    with archive.open('wb') as stream:
        subprocess.run(['git', '-C', str(root), 'archive', base], stdout=stream, check=True)
    with tarfile.open(archive) as source:
        source.extractall(before, filter='data')
    for label, tree in [('BEFORE', before), ('AFTER', root)]:
        print(f'{label}: cap=3, one peer worker and one local worker; '
              'try another worker, then canonical administrator', flush=True)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(tree), str(tree / 'tests')]))
        subprocess.run([sys.executable, str(probe)], cwd=temp, env=env, check=True)
