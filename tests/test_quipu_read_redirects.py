"""A budgeted read must not dispatch an uncharged redirect request."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.request import urlopen

import pytest

from shantytown import quipu_read_budget as budget


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('transport', ['plain', 'registry', 'events', 'deadline', 'plate'])
def test_redirect_dispatch_is_fenced_when_budget_enabled(tmp_path, monkeypatch, enabled, transport):
    counts = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            counts.append(self.path)
            if self.path != '/answer':
                self.send_response(303)
                self.send_header('Location', '/answer')
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"rows": [], "count": 0, "truncated": false}')

        do_POST = do_GET

        def log_message(self, *args):
            pass

    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    monkeypatch.setenv('ST_QUIPU_READS_PER_MINUTE', '2' if enabled else '0')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'

    from types import SimpleNamespace
    from shantytown import _deadline_http, quipu, quipu_events, seeds_plate
    from shantytown.protocols import EventsUnavailable

    def read():
        if transport == 'plain':
            with budget.open_read(origin, origin + '/first', timeout=2, opener=urlopen) as response:
                return response.read()
        if transport == 'registry':
            return quipu.QuipuRegistry(origin, onto='https://example.test/')._query('SELECT ?x WHERE {}')
        if transport == 'events':
            return quipu_events.QuipuEvents(origin, onto='https://example.test/')._get('/first')
        if transport == 'deadline':
            return _deadline_http.post(origin + '/first', '{}', {}, timeout=2, max_bytes=1024)
        return seeds_plate._query_wire(SimpleNamespace(quipu_url=origin), 'SELECT ?x WHERE {}', 2)

    try:
        if enabled:
            expected = {'registry': quipu.QuipuQueryRejected, 'events': EventsUnavailable}.get(
                transport, budget.ReadBudgetRefused)
            with pytest.raises(expected, match='redirect refused'):
                read()
            assert len(counts) == 1
            assert '/answer' not in counts
        else:
            read()
            assert len(counts) == 2
            assert counts[-1] == '/answer'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
