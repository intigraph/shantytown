"""Run from the repository root: python3 docs/demos/read-redirect-fence/demo.py."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.request import urlopen
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shantytown.quipu_read_budget import admit, open_read, ReadBudgetRefused

calls = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        calls.append(self.path)
        self.send_response(303 if self.path == '/start' else 200)
        if self.path == '/start':
            self.send_header('Location', '/answer')
        self.end_headers()

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
origin = f'http://127.0.0.1:{server.server_port}'
try:
    with TemporaryDirectory() as cache:
        for label, enabled in [('previous transport', True), ('fenced transport', True),
                               ('budget OFF control', False)]:
            calls.clear()
            with patch.dict(os.environ, XDG_CACHE_HOME=cache,
                            ST_QUIPU_READS_PER_MINUTE='10' if enabled else '0'):
                try:
                    if label == 'previous transport':
                        admit(origin)
                        response = urlopen(origin + '/start', timeout=2)
                    else:
                        response = open_read(origin, origin + '/start', timeout=2, opener=urlopen)
                    with response:
                        response.read()
                    result = 'completed'
                except ReadBudgetRefused:
                    result = 'redirect refused locally'
            print(f'{label}: {result}; requests={len(calls)}; paths={calls}')
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
