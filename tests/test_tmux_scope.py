"""Service cleanup must not own a server launched by the pane adapter."""
from pathlib import Path
import subprocess

import pytest

from shantytown import tmux_scope
from shantytown.tmux import Tmux


@pytest.mark.parametrize('path,expected', [
    ('/user.slice/user-1000.slice/user@1000.service/app.slice/tend.service', 'tend.service'),
    ('/user.slice/user-1000.slice/user@1000.service/app.slice/tend.service/child', 'tend.service'),
    ('/user.slice/user-1000.slice/user@1000.service/app.slice/tmux-spawn-x.scope', None),
    ('/user.slice/user-1000.slice/session-9.scope', None),
    ('/user.slice/user-1000.slice/user@1000.service', None),
    ('/system.slice/runner.service', None),
    ('/user.slice/user-2000.slice/user@2000.service/app.slice/tend.service', None),
    ('/', None),
])
def test_user_service_membership(path, expected):
    assert tmux_scope.user_service('0::' + path + '\n', 1000) == expected


def test_legacy_uses_systemd_hierarchy_not_cpu():
    assert tmux_scope.user_service(
        '3:cpu:/user@1000.service/not-the-owner.service\n'
        '2:name=systemd:/user@1000.service/app.slice/real.service\n', 1000) == 'real.service'


@pytest.mark.parametrize('raw', ['', 'garbage', '0::relative'])
def test_unknown_membership_is_not_a_safe_interactive_launch(raw):
    with pytest.raises(ValueError):
        tmux_scope.user_service(raw, 1000)


def _service(monkeypatch):
    monkeypatch.setattr(tmux_scope.sys, 'platform', 'linux')
    monkeypatch.setattr(tmux_scope.os, 'getuid', lambda: 1000)
    monkeypatch.setattr(Path, 'read_text', lambda *_a, **_k: '0::/user@1000.service/app.slice/tend.service\n')


def test_scope_preserves_literal_argv_and_unique_ownership(monkeypatch):
    _service(monkeypatch)
    command = ['tmux', '-L', 'test-only', 'new-session', '-d', '-s', '$literal']
    first = tmux_scope.launch_argv(command)
    second = tmux_scope.launch_argv(command)
    assert first[:6] == ['systemd-run', '--user', '--scope', '--quiet', '--collect', '--expand-environment=no']
    assert first[-len(command):] == command
    assert first[6] != second[6]
    assert first[6].startswith('--unit=st-tmux-')
    assert first[7] == '--'


def test_mac_never_reads_proc(monkeypatch):
    monkeypatch.setattr(tmux_scope.sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'read_text', lambda *_a, **_k: pytest.fail('Mac read /proc'))
    assert tmux_scope.launch_argv(['tmux']) == ['tmux']


def test_unreadable_linux_membership_refuses(monkeypatch):
    monkeypatch.setattr(tmux_scope.sys, 'platform', 'linux')
    def unreadable(*_a, **_k):
        raise PermissionError('fixture')
    monkeypatch.setattr(Path, 'read_text', unreadable)
    with pytest.raises(RuntimeError, match='service cgroup'):
        tmux_scope.launch_argv(['tmux'])


def test_scope_refusal_never_retries_bare_tmux(monkeypatch):
    _service(monkeypatch)
    pane = Tmux(socket='isolated-test')
    monkeypatch.setattr(pane, 'exists', lambda _name: False)
    calls = []
    def refused(argv, **kw):
        calls.append(argv)
        raise subprocess.CalledProcessError(1, argv)
    monkeypatch.setattr(subprocess, 'run', refused)
    with pytest.raises(subprocess.CalledProcessError):
        pane.new_session('empty-test')
    assert len(calls) == 1 and calls[0][0] == 'systemd-run'


def test_interactive_linux_scope_stays_direct(monkeypatch):
    monkeypatch.setattr(tmux_scope.sys, 'platform', 'linux')
    monkeypatch.setattr(tmux_scope.os, 'getuid', lambda: 1000)
    monkeypatch.setattr(Path, 'read_text', lambda *_a, **_k:
                        '0::/user@1000.service/app.slice/terminal.scope\n')
    assert tmux_scope.launch_argv(['tmux', 'new-session']) == ['tmux', 'new-session']


def test_new_session_keeps_sanitized_env_and_ownership_marker(monkeypatch):
    from shantytown import panemem
    _service(monkeypatch)
    pane = Tmux(socket='isolated-test')
    monkeypatch.setattr(pane, 'exists', lambda _name: False)
    monkeypatch.setattr(pane, '_bound_memory', lambda _name: None)
    env = {'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus'}
    monkeypatch.setattr(panemem, 'launch_env', lambda: env)
    calls = []
    def run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(subprocess, 'run', run)
    assert pane.new_session('empty-test') == 'empty-test'
    assert calls[0][0][0] == 'systemd-run'
    assert calls[0][1]['env'] is env
    assert calls[1][0][-4:] == ['-t', 'empty-test', 'SHANTY_OWNED', 'empty-test']
