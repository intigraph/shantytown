"""A hook's native session must reach the HTTP writer, even without session env."""
import pytest

from shantytown import owned_work_graph, quipu_auth, stats
from shantytown.quipu import request_headers
from test_quipu_provenance import context


@pytest.mark.parametrize('fail', [False, True])
def test_native_hook_session_reaches_publisher_and_does_not_escape(tmp_path, monkeypatch, fail):
    context(monkeypatch, CODEX_HOME='/fixture/codex', SHANTY_AGENT='fixture-agent',
            SHANTY_MODEL='fixture-model', CODEX_SESSION_ID='stale-environment-session')
    seen = []

    def publish(*args, **kwargs):
        seen.extend([request_headers(), quipu_auth.write_headers('https://fixture.invalid')])
        if fail:
            raise RuntimeError('fixture publication failure')

    monkeypatch.setattr(owned_work_graph, 'publish', publish)
    stats.capture(tmp_path, {'session_id': 'native-hook-session', 'hook_event_name': 'PreToolUse'})
    assert len(seen) == 2
    assert all(h['X-Quipu-Session'] == 'native-hook-session' for h in seen)
    assert request_headers()['X-Quipu-Session'] == 'stale-environment-session'


def test_hook_session_without_environment_session(tmp_path, monkeypatch):
    context(monkeypatch, CLAUDECODE='1', SHANTY_AGENT='fixture-agent', SHANTY_MODEL='fixture-model')
    seen = []
    monkeypatch.setattr(owned_work_graph, 'publish', lambda *a, **kw: seen.append(request_headers()))
    stats.capture(tmp_path, {'session_id': 'native-claude-session', 'hook_event_name': 'PreToolUse'})
    assert seen[0]['X-Quipu-Session'] == 'native-claude-session'
    assert 'X-Quipu-Session' not in request_headers()
