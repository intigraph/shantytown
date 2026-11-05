#!/usr/bin/env python3
"""Compare real base/head CLI card conversions in private fixtures. No launches."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
BASE = '7923c5cfc68057406a39c4aee6479f6e509954bf'
PROBE = r'''
import contextlib, io, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from shantytown import cli, harness
from shantytown.files import FilesRegistry
from shantytown.protocols import Agent
root = Path(sys.argv[2]); reg = FilesRegistry(root / 'crew')
reg.set(Agent(name='scratch', role='administrator', harness='claude',
              model='claude-fixture', chrome=True))
def switch(target, *flags):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return cli.main(['--root', str(root), '--backend', 'files', 'agent',
                         'harness', 'scratch', target, *flags])
assert switch('codex', '--model', 'codex-fixture') == 0
card = reg.get('scratch')
# Only compose the command; never start the process.
try:
    with contextlib.redirect_stderr(io.StringIO()):
        command = harness.get('codex').launch(card, str(root / 'codex/config.toml'))
    launch = 'COMPOSED; no Chrome flags' if '--chrome' not in command else 'WRONG FLAG'
except harness.Unsupported:
    launch = 'REFUSED: chrome'
rc = switch('claude'); restored = reg.get('scratch')
print(json.dumps(dict(codex_chrome=card.chrome, codex_command=launch,
                     return_code=rc, restored=rc == 0 and restored.chrome
                     and restored.model == 'claude-fixture'), sort_keys=True))
'''

with tempfile.TemporaryDirectory() as folder:
    scratch = Path(folder)
    archived = subprocess.check_output(['git', '-C', str(ROOT), 'archive', BASE, 'shantytown'])
    base = scratch / 'base'; base.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archived)) as archive:
        # The exact committed package is the comparison, not a reimplementation.
        for member in archive.getmembers():
            path = Path(member.name)
            assert not path.is_absolute() and '..' not in path.parts
            if member.isfile():
                target = base / path; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
    for label, source in [('BEFORE', base), ('AFTER', ROOT)]:
        started = time.monotonic()
        output = subprocess.check_output([sys.executable, '-c', PROBE, str(source),
                                          str(scratch / label)], text=True)
        print(label + ': ' + output.strip())
        print(f'elapsed_seconds: {time.monotonic() - started:.3f}')
