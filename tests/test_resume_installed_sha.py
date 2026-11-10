"""Full serving commit identity, including the actual stored-marker reader."""
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

import pytest

from shantytown import deferrals, resume_kinds

SHA = 'a' * 40
OTHER = 'b' * 40


@pytest.fixture
def version_server(tmp_path, monkeypatch):
    state = {'body': json.dumps({'version': '0.17.0', 'git_sha': SHA, 'git_dirty': False}).encode(),
             'status': 200, 'requests': [], 'redirect': False, 'length_delta': 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state['requests'].append(self.path)
            self.send_response(302 if state['redirect'] else state['status'])
            if state['redirect']:
                self.send_header('Location', f'http://127.0.0.1:{self.server.server_port}/elsewhere')
            self.send_header('Content-Length', str(len(state['body']) + state['length_delta']))
            self.end_headers()
            self.wfile.write(state['body'])
            self.close_connection = True

        def log_message(self, *args):
            pass

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    root = tmp_path / 'deployment'
    root.mkdir()
    origin = f'http://127.0.0.1:{server.server_port}'
    (root / 'shantytown.toml').write_text(f'[env]\nQUIPU_SERVER = "{origin}"\n')
    monkeypatch.setenv('SHANTY_ROOT', str(root))
    monkeypatch.setenv('QUIPU_SERVER', 'http://unused.invalid')  # persisted origin wins
    monkeypatch.setenv('QUIPU_AUTH_TOKEN', 'isolated-test-token')
    state['root'] = root
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_exact_served_identity_does_not_read_local_cli(version_server):
    def forbidden(*args):
        pytest.fail('SHA serving condition must not run a local CLI')
    assert resume_kinds.installed('quipu@' + SHA, run=forbidden, which=forbidden)[0] is True
    assert resume_kinds.installed('quipu==' + SHA, run=forbidden, which=forbidden)[0] is True
    assert version_server['requests'] == ['/version', '/version']


def test_same_version_different_sha_is_not_met(version_server):
    assert resume_kinds.installed('quipu@' + OTHER)[0] is False


@pytest.mark.parametrize('target', ['a' * 8, 'a' * 39, 'a' * 41, 'g' * 40,
                                    '1' * 8, '1' * 39, '1' * 41, 'A' * 40])
def test_ambiguous_or_malformed_commit_refused(target):
    with pytest.raises(ValueError):
        resume_kinds.validate('installed', 'quipu@' + target)


@pytest.mark.parametrize('arg', ['quipu>=' + SHA, 'quipu>' + SHA, 'sd@' + SHA,
                                 'rm@' + SHA, 'bobbin@' + '1' * 40])
def test_commit_ordering_or_unconfigured_tool_refused(arg):
    with pytest.raises(ValueError):
        resume_kinds.validate('installed', arg)


@pytest.mark.parametrize('identity', [
    {}, {'git_sha': SHA}, {'git_sha': SHA, 'git_dirty': True},
    {'git_sha': SHA, 'git_dirty': 0}, {'git_sha': SHA, 'git_dirty': 'false'},
    {'git_sha': 'a' * 39, 'git_dirty': False}, {'git_sha': 'a' * 41, 'git_dirty': False},
    {'git_sha': 'g' * 40, 'git_dirty': False}, {'git_sha': None, 'git_dirty': False}, [],
])
def test_unknown_identity_never_wakes(version_server, identity):
    version_server['body'] = json.dumps(identity).encode()
    assert resume_kinds.evaluate('installed', 'quipu@' + SHA)[0] is None


@pytest.mark.parametrize('body', [b'not JSON', b'{', b'{"git_sha":"' + SHA.encode()
                                  + b'","git_sha":"' + SHA.encode() + b'","git_dirty":false}',
                                  b' ' * 8193, b'[' * 1100 + b']' * 1100, b'{"git_sha":"' + SHA.encode()
                                  + b'","git_dirty":false,"extra":NaN}'])
def test_incomplete_duplicate_or_oversized_json_unknown(version_server, body):
    version_server['body'] = body
    assert resume_kinds.installed('quipu@' + SHA)[0] is None


@pytest.mark.parametrize('fault', ['http_error', 'redirect', 'incomplete'])
def test_failed_http_never_wakes_or_follows_redirect(version_server, fault):
    if fault == 'http_error':
        version_server['status'] = 503
    elif fault == 'redirect':
        version_server['redirect'] = True
    else:
        version_server['length_delta'] = 100
    assert resume_kinds.installed('quipu@' + SHA)[0] is None
    assert version_server['requests'] == ['/version']


def test_config_error_does_not_fall_back_to_ambient_origin(version_server):
    (version_server['root'] / 'shantytown.toml').write_text('broken[')
    assert resume_kinds.installed('quipu@' + SHA)[0] is None
    assert version_server['requests'] == []


def test_real_stored_condition_reader_uses_controlled_serving_response(version_server, tmp_path):
    from shantytown.dispatch import Dispatcher
    from shantytown.files import FilesRegistry, FilesTracker
    from shantytown.tmux import NullPanes
    tracker = FilesTracker(tmp_path / 'items')
    tracker.update('item-1', title='serving identity fixture', status='open', assignee='wu', priority=2)
    dispatcher = Dispatcher(FilesRegistry(tmp_path / 'crew'), tracker, NullPanes())
    dispatcher.defer('item-1', 'external', 'resume_when: installed:quipu@' + SHA,
                     until='2099-11-11T04:00:00Z')
    stored = tracker.get('item-1')
    rows = [{'id': stored.id, 'status': stored.status, 'notes': stored.notes, 'labels': []}]
    [finding] = deferrals.evaluate(rows, datetime.now(timezone.utc))
    assert finding.met is True and not finding.untestable
    version_server['body'] = json.dumps({'version': '0.17.0', 'git_sha': OTHER, 'git_dirty': False}).encode()
    assert deferrals.evaluate(rows, datetime.now(timezone.utc)) == []  # known unmet stays silent
    version_server['body'] = json.dumps({'version': '0.17.0', 'git_sha': SHA, 'git_dirty': True}).encode()
    [finding] = deferrals.evaluate(rows, datetime.now(timezone.utc))
    assert not finding.met and finding.untestable
    assert version_server['requests'] == ['/version'] * 3


@pytest.mark.parametrize('origin', ['', 'http://user:password@127.0.0.1',
                                    'http://127.0.0.1?elsewhere', 'file:///tmp/version'])
def test_unconfigured_or_invalid_origin_does_not_make_requests(version_server, monkeypatch, origin):
    (version_server['root'] / 'shantytown.toml').write_text('[env]\n')
    monkeypatch.setenv('QUIPU_SERVER', origin)
    assert resume_kinds.installed('quipu@' + SHA)[0] is None
    assert version_server['requests'] == []
