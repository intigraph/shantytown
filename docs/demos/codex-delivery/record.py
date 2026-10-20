"""Run the identical probe against an exported base and the current checkout."""
from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

repo = Path(__file__).resolve().parents[3]
probe = Path(__file__).with_name('probe.py')
base = '90ff87992594efa46f58d54bb405c2f979749e22'
with TemporaryDirectory(prefix='codex-delivery-base-') as directory:
    target = Path(directory)
    archive = target / 'base.tar'
    with archive.open('wb') as stream:
        subprocess.run(['git', '-C', str(repo), 'archive', base], stdout=stream, check=True)
    checkout = target / 'checkout'
    checkout.mkdir()
    subprocess.run(['tar', '-xf', str(archive), '-C', str(checkout)], check=True)
    head = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    for label, source in [('BASE ' + base, checkout), ('CANDIDATE ' + head, repo)]:
        print(label + ' (private synthetic panes)', flush=True)
        env = dict(os.environ, PYTHONPATH=str(source))
        subprocess.run([sys.executable, str(probe)], cwd=source, env=env, check=True)
        time.sleep(0.8)
