"""Loopback-only before/after recording: command labels, never arguments."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import ModuleType
from unittest.mock import patch
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--base', default='0c0820fbc89885239c8662b6c1c4041eb32f14c5')
args = parser.parse_args()
root = Path(__file__).resolve().parents[3]
before = ModuleType('before_identity')
exec(subprocess.check_output(['git', 'show', args.base + ':shantytown/query_identity.py'], cwd=root), before.__dict__)
spec = importlib.util.spec_from_file_location('after_identity', root / 'shantytown/query_identity.py')
after = importlib.util.module_from_spec(spec)
spec.loader.exec_module(after)
seen = []

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        seen.append({key: self.headers.get(header) for key, header in (
            ('source', 'X-Quipu-Source'), ('operation', 'X-Quipu-Operation'))})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
worker = threading.Thread(target=server.serve_forever, daemon=True)
worker.start()

def send(module):
    headers = {'X-Quipu-Client': 'seeds', **module.read_headers()}
    with urlopen(Request(f'http://127.0.0.1:{server.server_port}/probe', headers=headers), timeout=2) as response:
        assert response.status == 200
    return seen[-1]

try:
    with patch.dict(os.environ, {}, clear=True):
        print(json.dumps({'before': send(before)}, sort_keys=True))
        with after.declared_command('anchor'):
            print(json.dumps({'after': send(after)}, sort_keys=True))
            with after.declared_command('inbox'):
                assert send(after)['source'] == 'st-anchor'
        with after.declared_command('private argument'):
            result = send(after)
            assert result['source'] == 'st-other'
            print(json.dumps({'argument_refusal_control': result}, sort_keys=True))
        assert after.read_headers()['X-Quipu-Source'] == 'shantytown'
        print('PASS: loopback HTTP only; outer command retained; context restored')
finally:
    server.shutdown()
    server.server_close()
    worker.join()
