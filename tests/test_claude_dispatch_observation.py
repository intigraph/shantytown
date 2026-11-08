"""Actual terminal adapter: old echo and occupied composer never prove send."""
from types import SimpleNamespace

import pytest

from shantytown.tmux import Tmux


def run(monkeypatch, after, *, before='\x1b[39m❯ ', birth_after=123):
    panes = Tmux(socket='test-only')
    monkeypatch.setattr(panes, '_refuse_in_mode', lambda *a, **k: None)
    monkeypatch.setattr(panes, 'foreground', lambda _: 'claude')
    monkeypatch.setattr(panes, 'capture', lambda *a, **k: before)
    frames = iter([before, after, after, after])
    monkeypatch.setattr(panes, '_claude_history', lambda _: next(frames))
    births = iter([123, birth_after, birth_after, birth_after])
    monkeypatch.setattr(panes, 'session_created', lambda _: next(births))
    monkeypatch.setattr('shantytown.tmux.subprocess.run', lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout='', stderr=''))
    monkeypatch.setattr('shantytown.tmux.time.sleep', lambda _: None)
    return panes._send('%5', 'exact body [unique attempt]')


def test_new_exact_body_with_empty_composer_is_observed(monkeypatch):
    result = run(monkeypatch, '❯ exact body [unique attempt]\nWorking…\n\x1b[39m❯ ')
    assert result.matches('%5', 'exact body [unique attempt]')


@pytest.mark.parametrize('after,before,birth', [
    ('❯ exact body [unique attempt]', '\x1b[39m❯ ', 123),
    ('exact body [unique attempt]\n\x1b[39m❯ ', 'exact body [unique attempt]\n\x1b[39m❯ ', 123),
    ('quoted different body [unique attempt]\n\x1b[39m❯ ', '\x1b[39m❯ ', 123),
    ('exact  body [unique attempt]\n\x1b[39m❯ ', '\x1b[39m❯ ', 123),
    ('exact body [unique attempt]\n\x1b[39m❯ ', '\x1b[39m❯ ', 124),
])
def test_stranded_old_similar_or_restarted_session_is_not_proof(monkeypatch, after, before, birth):
    assert run(monkeypatch, after, before=before, birth_after=birth) is None
