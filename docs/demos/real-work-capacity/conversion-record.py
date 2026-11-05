"""Record both versions using only temporary stores, identities and HOME."""
import os
from pathlib import Path
import subprocess
import sys

probe = Path(__file__).with_name('conversion-probe.py')
for mode, variable in [('buggy', 'CAPACITY_BASE_SOURCE'), ('fixed', 'CAPACITY_HEAD_SOURCE')]:
    print(mode, flush=True)
    subprocess.run([sys.executable, str(probe), mode], check=True,
                   env=dict(os.environ, PYTHONPATH=os.environ[variable]))
