"""Portable same-user launch evidence; unknown is never hookless."""
import io
import os
from types import SimpleNamespace

import pytest

from shantytown import tmux
from shantytown.runtime import live_wiring


@pytest.mark.parametrize('tail', [
    'NOTE=hello CODEX_HOME=/tmp/false-home',
    'CODEX_HOME=/tmp/real NOTE=assignment-like-text',
    'NOTE=hello CLAUDE_CONFIG_DIR=/tmp/false-home',
])
def test_flattened_environment_cannot_prove_assignment_boundaries(monkeypatch, tail):
    monkeypatch.setattr(tmux.sys, 'platform', 'darwin')
    monkeypatch.setattr(tmux.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=f'{os.getuid()} codex {tail}'))
    assert tmux.Tmux._launch_line('123', 'codex') is None


def test_darwin_does_not_collect_lossy_private_environment(monkeypatch):
    monkeypatch.setattr(tmux.sys, 'platform', 'darwin')
    args = 'codex --model example'
    def run(command, **kwargs):
        raise AssertionError('lossy environment must not be collected')
    monkeypatch.setattr(tmux.subprocess, 'run', run)
    line = tmux.Tmux._launch_line('123', args)
    assert line is None


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


def test_darwin_argv_carried_pointer_still_reads_configured_worker_send(tmp_path, monkeypatch):
    from shantytown import codex
    home = tmp_path / 'codexhome'
    home.mkdir()
    (home / 'config.toml').write_text(codex.render(codex.settings_for_role('worker', root=tmp_path)))
    monkeypatch.setattr(tmux.sys, 'platform', 'darwin')
    monkeypatch.setattr(tmux.subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(
        AssertionError('environment collection')))
    wiring = live_wiring('pane', lambda _: tmux.Tmux._launch_line('123', f'CODEX_HOME={home} codex'))
    assert wiring is not None and 'send' in wiring.directions
    assert wiring.settings_path == str(home / 'config.toml')


def test_darwin_environment_absence_is_unknown_not_hookless(monkeypatch):
    monkeypatch.setattr(tmux.sys, 'platform', 'darwin')
    monkeypatch.setattr(tmux.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=f'{os.getuid()} codex PATH=/bin'))
    line = tmux.Tmux._launch_line('123', 'codex')
    assert line is None and live_wiring('pane', lambda _: line) is None


def test_unknown_candidate_does_not_become_shell_fallback(monkeypatch):
    monkeypatch.setattr(tmux.sys, 'platform', 'linux')
    def run(command, **kwargs):
        if command[0] == 'tmux':
            return SimpleNamespace(returncode=0, stdout='123 pane %1\n')
        return SimpleNamespace(returncode=0, stdout='100 123 sh\n90 124 codex\n')
    monkeypatch.setattr(tmux.subprocess, 'run', run)
    monkeypatch.setattr(tmux.Tmux, '_launch_line', staticmethod(lambda pid, args: None if args == 'codex' else args))
    assert tmux.Tmux().cmdline('pane') is None
