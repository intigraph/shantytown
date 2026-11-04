"""Run the same fixture against base and candidate; no namespace or live writes."""
import json
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

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
    os.environ.pop('SHANTY_PHYSICAL_HOST')
    with patch.object(socket, 'gethostname', return_value='Host-A.example'):
        print('rollback producer preserved:', graph.producer(root) == original)
