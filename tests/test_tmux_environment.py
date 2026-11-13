"""Portable same-user launch evidence; unknown is never hookless."""
import io
import os
from types import SimpleNamespace

import pytest

from shantytown import tmux
from shantytown.runtime import live_wiring


def test_darwin_declared_pointer_only(monkeypatch):
    monkeypatch.setattr(tmux.sys, 'platform', 'darwin')
    args = 'codex --model example'
    def run(command, **kwargs):
        assert command == ['ps', 'eww', '-o', 'uid=,command=', '-p', '123']
        assert kwargs['timeout'] == 2
        return SimpleNamespace(returncode=0, stdout=f'{os.getuid()} {args} CODEX_HOME=/private/config SECRET_TOKEN=hidden PATH=/bin\n')
    monkeypatch.setattr(tmux.subprocess, 'run', run)
    line = tmux.Tmux._launch_line('123', args)
    assert line == 'CODEX_HOME=/private/config ' + args
    assert 'hidden' not in line and 'PATH=' not in line


@pytest.mark.parametrize('output', ['', '999999 codex CODEX_HOME=/config',
    f'{os.getuid()} other CODEX_HOME=/config',
    f'{os.getuid()} codex CODEX_HOME=/path with spaces SECRET=x',
    f'{os.getuid()} codex CODEX_HOME=/a CODEX_HOME=/b'])
def test_darwin_ambiguous_environment_is_unknown(monkeypatch, output):
    monkeypatch.setattr(tmux.sys, 'platform', 'darwin')
    monkeypatch.setattr(tmux.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=output))
    assert tmux.Tmux._launch_line('123', 'codex') is None


def test_unreadable_environment_is_unknown_not_hookless(monkeypatch):
    monkeypatch.setattr(tmux.sys, 'platform', 'linux')
    monkeypatch.setattr('builtins.open', lambda *a, **k: (_ for _ in ()).throw(PermissionError()))
    line = tmux.Tmux._launch_line('123', 'codex')
    assert line is None
    assert live_wiring('pane', lambda _: line) is None
    assert tmux.Tmux._launch_line('123', 'claude --settings /config.json') == 'claude --settings /config.json'


def test_readable_absent_pointer_is_measured_hookless(monkeypatch):
    monkeypatch.setattr(tmux.sys, 'platform', 'linux')
    monkeypatch.setattr('builtins.open', lambda *a, **k: io.BytesIO(b'PATH=/bin\0SECRET=x\0'))
    line = tmux.Tmux._launch_line('123', 'codex')
    assert line == 'codex'
    assert live_wiring('pane', lambda _: line).directions == set()


def test_darwin_configured_worker_reads_send(tmp_path, monkeypatch):
    from shantytown import codex
    home = tmp_path / 'codexhome'
    home.mkdir()
    (home / 'config.toml').write_text(codex.render(codex.settings_for_role('worker', root=tmp_path)))
    monkeypatch.setattr(tmux.sys, 'platform', 'darwin')
    monkeypatch.setattr(tmux.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=f'{os.getuid()} codex CODEX_HOME={home} SECRET_TOKEN=hidden'))
    wiring = live_wiring('pane', lambda _: tmux.Tmux._launch_line('123', 'codex'))
    assert wiring is not None and 'send' in wiring.directions
    assert wiring.settings_path == str(home / 'config.toml')


def test_darwin_readable_no_pointer_is_hookless(monkeypatch):
    monkeypatch.setattr(tmux.sys, 'platform', 'darwin')
    monkeypatch.setattr(tmux.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=f'{os.getuid()} codex PATH=/bin'))
    line = tmux.Tmux._launch_line('123', 'codex')
    assert live_wiring('pane', lambda _: line).directions == set()


def test_unknown_candidate_does_not_become_shell_fallback(monkeypatch):
    monkeypatch.setattr(tmux.sys, 'platform', 'linux')
    def run(command, **kwargs):
        if command[0] == 'tmux':
            return SimpleNamespace(returncode=0, stdout='123 pane %1\n')
        return SimpleNamespace(returncode=0, stdout='100 123 sh\n90 124 codex\n')
    monkeypatch.setattr(tmux.subprocess, 'run', run)
    monkeypatch.setattr(tmux.Tmux, '_launch_line', staticmethod(lambda pid, args: None if args == 'codex' else args))
    assert tmux.Tmux().cmdline('pane') is None
