"""Run the same fixture against base and candidate; no namespace or live writes."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from shantytown import harness
from shantytown.protocols import Agent
from shantytown import governor_metrics as metrics
from shantytown import owned_work_graph as graph
from shantytown import query_identity, quipu_provenance

# No real machine names, credentials, network, crew homes or graph mutations.
os.environ.pop('SHANTY_PHYSICAL_HOST', None)
os.environ.pop('QUIPU_HOST', None)
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    with patch.object(socket, 'gethostname', return_value='Host-A.example'):
        original = graph.producer(root)
    os.environ['SHANTY_PHYSICAL_HOST'] = 'Host-A.example'
    calls = []
    with patch.object(socket, 'gethostname', return_value='ada'), \
            patch.object(os, 'uname', return_value=SimpleNamespace(nodename='ada')), \
            patch.object(metrics, '_push', side_effect=lambda url, job, instance, body, **kw: calls.append(instance)):
        print('fixture: kernel hostname=ada; original physical hostname=Host-A.example')
        print('lifecycle producer preserved:', graph.producer(root) == original)
        print('Quipu read host:', query_identity.read_headers()['X-Quipu-Host'])
        print('Quipu write host:', quipu_provenance.headers()['X-Quipu-Host'])
        metrics.publish(root, [], url='http://metrics.invalid', env={})
        print('governor telemetry instances:', json.dumps(calls))
        binary = root / 'bin/codex'
        binary.parent.mkdir()
        binary.write_text('#!/usr/bin/python3\nimport os\nprint(os.environ.get("QUIPU_HOST", "UNSET"))\n')
        binary.chmod(0o755)
        os.environ['PATH'] = str(binary.parent) + os.pathsep + os.environ['PATH']
        command = harness.get('codex').launch(Agent(name='ada', role='worker'), str(root / 'config.toml'))
        child = subprocess.run(['/bin/sh', '-c', command], capture_output=True, text=True, check=True)
        print('actual fake-tool child QUIPU_HOST:', child.stdout.strip())
    os.environ.pop('SHANTY_PHYSICAL_HOST')
    with patch.object(socket, 'gethostname', return_value='Host-A.example'):
        print('rollback producer preserved:', graph.producer(root) == original)
