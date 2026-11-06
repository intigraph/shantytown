"""Run the same isolated probe on the retained baseline and candidate."""
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

root = Path(__file__).resolve().parents[3]
baseline = 'fa4d7e08e1ae25c9da160553b463afeb99a1baa2'
candidate = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
driver = Path(__file__).with_name('demo.py')
with tempfile.TemporaryDirectory() as directory:
    before = Path(directory)
    archive = subprocess.check_output(['git', '-C', str(root), 'archive', baseline])
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(before, filter='data')
    print('SYNTHETIC FIXTURE: 15 held gates, capacity 12, prior failure count 2', flush=True)
    for label, checkout, expected in [('BEFORE ' + baseline, before, 'legacy'),
                                      ('AFTER ' + candidate, root, 'fixed')]:
        print(label, flush=True)
        subprocess.run([sys.executable, '-B', str(driver), '--source', str(checkout),
                        '--expect', expected], check=True)
