"""The real HTTP helper must carry context; a client label alone is not provenance."""
import json

from shantytown import quipu_auth
from shantytown.quipu import QuipuRegistry, request_headers


KEYS = ('QUIPU_AGENT', 'QUIPU_HARNESS', 'QUIPU_MODEL', 'QUIPU_SESSION', 'QUIPU_HOST',
        'SHANTY_AGENT', 'SHANTY_MODEL', 'CLAUDECODE', 'CLAUDE_CODE_SESSION_ID',
        'CODEX_HOME', 'CODEX_SESSION_ID', 'CODEX_THREAD_ID')


def context(monkeypatch, **values):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(quipu_auth, 'token', lambda: 'fixture-only')
    monkeypatch.setattr(quipu_auth, 'status', lambda _: 'ready')


def test_actual_transport_helpers_carry_verified_context_inputs(monkeypatch):
    context(monkeypatch, QUIPU_AGENT='fixture-agent', QUIPU_HARNESS='codex',
            QUIPU_MODEL='fixture-model', QUIPU_SESSION='fixture-session', QUIPU_HOST='fixture-host')
    for headers in (request_headers(), quipu_auth.write_headers('https://fixture.invalid')):
        assert headers['Authorization'] == 'Bearer fixture-only'
        for field, value in [('Agent', 'fixture-agent'), ('Harness', 'codex'),
                             ('Model', 'fixture-model'), ('Session', 'fixture-session'),
                             ('Host', 'fixture-host')]:
            assert headers['X-Quipu-' + field] == value


def test_knot_wire_retains_client_and_provenance(monkeypatch):
    context(monkeypatch, CODEX_HOME='/fixture/codex', SHANTY_AGENT='fixture-agent',
            SHANTY_MODEL='fixture-model', CODEX_THREAD_ID='fixture-thread')
    seen = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps({'conforms': True, 'count': 1, 'tx_id': 1}).encode()

    def send(req, **kwargs):
        seen.append({k.lower(): v for k, v in req.header_items()})
        return Response()

    monkeypatch.setattr('urllib.request.urlopen', send)
    QuipuRegistry(server='https://fixture.invalid', client_label='fixture-client', onto='https://fixture.invalid/ontology/')._knot('fixture')
    assert seen[0]['x-quipu-client'] == 'fixture-client'
    assert seen[0]['x-quipu-agent'] == 'fixture-agent'
    assert seen[0]['x-quipu-session'] == 'fixture-thread'


def test_standalone_producer_does_not_inherit_an_agent(monkeypatch):
    context(monkeypatch, SHANTY_AGENT='unrelated-agent')
    headers = request_headers()
    assert headers['X-Quipu-Agent'] == 'shantytown'
    assert headers['X-Quipu-Harness'] == 'cli'
    assert 'X-Quipu-Session' not in headers
    assert 'X-Quipu-Model' not in headers


def test_codex_uses_own_session_and_missing_fields_stay_missing(monkeypatch):
    context(monkeypatch, CODEX_HOME='/fixture/codex', CODEX_SESSION_ID='codex-session',
            CLAUDE_CODE_SESSION_ID='stale-claude')
    headers = request_headers()
    assert headers['X-Quipu-Harness'] == 'codex'
    assert headers['X-Quipu-Session'] == 'codex-session'
    assert 'X-Quipu-Agent' not in headers
    assert 'X-Quipu-Model' not in headers


def test_claude_session_and_explicit_override_precedence(monkeypatch):
    context(monkeypatch, CLAUDECODE='1', SHANTY_AGENT='fixture-agent', SHANTY_MODEL='fixture-model',
            CLAUDE_CODE_SESSION_ID='claude-session', QUIPU_SESSION='explicit-session')
    headers = request_headers()
    assert headers['X-Quipu-Harness'] == 'claude'
    assert headers['X-Quipu-Session'] == 'explicit-session'
    assert headers['X-Quipu-Model'] == 'fixture-model'


def test_header_values_are_bounded_without_injection(monkeypatch):
    context(monkeypatch, QUIPU_AGENT=' \r\nfixture\x01é ', QUIPU_HOST='h' * 200,
            QUIPU_MODEL='\r\n')
    headers = request_headers()
    assert headers['X-Quipu-Agent'] == 'fixture'
    assert headers['X-Quipu-Host'] == 'h' * 128
    assert 'X-Quipu-Model' not in headers


def test_missing_credential_still_refuses_before_write(monkeypatch):
    import pytest
    context(monkeypatch, QUIPU_AGENT='fixture-agent')
    monkeypatch.setattr(quipu_auth, 'token', lambda: '')
    with pytest.raises(quipu_auth.CredentialRefused):
        quipu_auth.write_headers('https://fixture.invalid')


def test_hook_session_is_local_to_its_thread_and_nested_scope(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from shantytown.quipu_provenance import hook_session
    context(monkeypatch, CODEX_HOME='/fixture/codex')
    with ThreadPoolExecutor(max_workers=1) as pool:
        with hook_session('outer-native-session'):
            assert 'X-Quipu-Session' not in pool.submit(request_headers).result()
            with hook_session('inner-native-session'):
                assert request_headers()['X-Quipu-Session'] == 'inner-native-session'
            assert request_headers()['X-Quipu-Session'] == 'outer-native-session'
    assert 'X-Quipu-Session' not in request_headers()
