#!/usr/bin/env python3
"""Run the actual PR-event guard with private synthetic event files."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[3]
with tempfile.TemporaryDirectory() as directory:
    event = Path(directory) / 'event.json'
    for title, expected in [('Enforce ten-item local assignment cap', 1),
                            ('fix(assignments): enforce ten-item local cap', 0),
                            ('test: cover status variants', 0)]:
        event.write_text(json.dumps({'pull_request': {'title': title}}))
        env = dict(os.environ, GITHUB_EVENT_NAME='pull_request', GITHUB_EVENT_PATH=str(event))
        run = subprocess.run([sys.executable, str(root / 'scripts/check-pr-title.py')],
                             env=env, capture_output=True, text=True)
        print(f'{title!r}: exit {run.returncode}')
        print((run.stdout + run.stderr).strip())
        assert run.returncode == expected
