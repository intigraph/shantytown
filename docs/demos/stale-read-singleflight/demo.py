#!/usr/bin/env python3
"""Local source fixture: concurrent stale reads and an exact-read control."""
import argparse
import hashlib
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

parser = argparse.ArgumentParser()
parser.add_argument('--source-tree', default='.')
args = parser.parse_args()
sys.path.insert(0, str(Path(args.source_tree).resolve()))
from shantytown import seeds_plate, seeds_read_cache  # noqa: E402
cache_source = Path(seeds_read_cache.__file__)
flight_source = cache_source.with_name('seeds_read_flight.py')
print(json.dumps({
    'read_cache_sha256': hashlib.sha256(cache_source.read_bytes()).hexdigest(),
    'flight_sha256': hashlib.sha256(flight_source.read_bytes()).hexdigest() if flight_source.exists() else None,
}))

with tempfile.TemporaryDirectory(prefix='singleflight-demo-') as scratch:
    os.environ.update(XDG_CACHE_HOME=scratch, ST_SEEDS_READ_CACHE='1', ST_SEEDS_STALE_TTL='60', QUIPU_PRIORITY='')
    state = {'queries': 0, 'watermarks': 0}
    mutex = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, value):
            body = json.dumps(value).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            with mutex:
                state['watermarks'] += 1
            self.reply({'store_id': 'demo-store', 'watermark_tx': 1})

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            with mutex:
                state['queries'] += 1
            time.sleep(.2)
            self.reply({'rows': [{'value': 'populated-control'}], 'count': 1, 'truncated': False})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proof = SimpleNamespace(quipu_url=f'http://127.0.0.1:{server.server_port}')
    barrier = threading.Barrier(8)

    def read():
        return seeds_plate._query(proof, 'SELECT demo-owner', 5)

    def caller(_):
        with seeds_read_cache.stale_ok():
            barrier.wait(timeout=5)
            return read()

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(caller, range(8)))
        assert all(r['rows'] == [{'value': 'populated-control'}] for r in results)
        print(json.dumps({'callers': 8, 'populated_answers': len(results), 'wire_queries': state['queries']}))
        before = state['queries']
        assert read()['count'] == 1
        print(json.dumps({'exact_read_additional_wire_queries': state['queries'] - before}))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
