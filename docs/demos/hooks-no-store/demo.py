#!/usr/bin/env python3
"""Actual CLI in isolated source fixtures; never uses a live crew store."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

repo = Path(__file__).resolve().parents[3]
base = 'f909de3e3ba445946545dd673f94edea1de2d0fd'
candidate = 'c2e9919e'
for revision in (base, candidate):
    with tempfile.TemporaryDirectory(prefix='hooks-no-store-') as temporary:
        fixture = Path(temporary)
        source, home = fixture/'source', fixture/'home'
        source.mkdir()
        home.mkdir()
        data = subprocess.check_output(['git', '-C', str(repo), 'archive', revision, 'shantytown'])
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(source, filter='data')
        environment = {'HOME': str(home), 'PATH': os.environ['PATH'], 'PYTHONPATH': str(source)}
        command = [sys.executable, '-c', 'from shantytown.cli import main; raise SystemExit(main())',
                   'ops', 'hooks', 'check', '--json']
        for existing in (False, True):
            probe = command
            if existing:
                (home/'.shanty').mkdir()
                probe = command[:3] + ['--root', str(home/'.shanty')] + command[3:]
            result = subprocess.run(probe, env=environment, cwd='/', capture_output=True,
                                    text=True, timeout=20)
            report = json.loads(result.stdout)
            print(json.dumps({'revision': revision[:8], 'existing_store': existing,
                'cwd': '/', 'exit': result.returncode, 'items': report['summary']['items'],
                'store_error': report.get('store_error')}, sort_keys=True))
            assert result.returncode == (2 if revision == candidate and not existing else 0)
            assert report['summary']['items'] == 0
