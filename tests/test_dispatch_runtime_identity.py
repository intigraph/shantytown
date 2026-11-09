import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from shantytown.tmux import Tmux


def test_process_start_and_pid_are_bound_even_when_argv_and_tmux_birth_match(monkeypatch):
    panes = Tmux(socket='test-only')
    monkeypatch.setattr(panes, '_runtime_process', lambda _: ('123', 'codex --fixture'))
    fields = ['S'] + ['0'] * 18 + ['456']
    boot = '00000000-0000-0000-0000-000000000001'
    monkeypatch.setattr(Path, 'read_text', lambda p: boot if p.name == 'boot_id'
                        else '123 (name with ) spaces) ' + ' '.join(fields))
    first = panes.runtime_identity('worker')
    assert first == hashlib.sha256(f'123:{boot}:456:codex --fixture'.encode()).hexdigest()
    fields[-1] = '789'
    assert panes.runtime_identity('worker') != first


def test_unreadable_process_does_not_borrow_session_identity(monkeypatch):
    panes = Tmux(socket='test-only')
    monkeypatch.setattr(panes, '_runtime_process', lambda _: ('123', 'codex --fixture'))
    monkeypatch.setattr(Path, 'read_text', lambda _: (_ for _ in ()).throw(PermissionError()))
    assert panes.runtime_identity('worker') is None
