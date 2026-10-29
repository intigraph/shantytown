"""Darwin rejects GNU ps flags: missing observations must never invent MANUAL."""
import subprocess

import pytest

from shantytown import launchable
from shantytown.tmux import Tmux


@pytest.mark.parametrize('platform', ['darwin', 'linux'])
@pytest.mark.parametrize('bypass', [True, False])
def test_scoped_native_probe_observes_actual_launch(monkeypatch, platform, bypass):
    monkeypatch.setattr('shantytown.tmux.sys.platform', platform)
    flag = ' --dangerously-bypass-approvals-and-sandbox' if bypass else ''
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == 'tmux':
            return subprocess.CompletedProcess(cmd, 0, '100 st-worker\n', '')
        assert kwargs['timeout'] == 2
        if cmd[0] == 'pgrep':
            assert cmd == ['pgrep', '-a', '-P', '100']
            return subprocess.CompletedProcess(cmd, 0, '101\n', '')
        if platform == 'darwin':
            # The old query genuinely fails on Darwin, rather than a mock
            # accepting any ps invocation and hiding the original regression.
            if '--ppid' in cmd or 'etimes=,pid=,args=' in cmd:
                return subprocess.CompletedProcess(cmd, 1, '', 'unsupported')
            assert cmd == ['ps', '-ww', '-o', 'etime=,pid=,args=', '-p', '100,101']
            age = '1-02:03:04'
        else:
            assert cmd == ['ps', '-ww', '-o', 'etimes=,pid=,args=', '-p', '100', '--ppid', '100']
            age = '93784'
        return subprocess.CompletedProcess(cmd, 0, f'{age} 100 -zsh\n{age} 101 codex{flag}\n', '')

    monkeypatch.setattr(subprocess, 'run', run)
    line = Tmux().cmdline('st-worker')
    assert line == f'codex{flag}'
    assert launchable.observed_posture('› ready', True, line) == (
        launchable.BYPASS if bypass else launchable.MANUAL)


@pytest.mark.parametrize('failure', ['denied', 'timeout', 'missing', 'malformed', 'too-many'])
def test_failed_darwin_observation_stays_unknown(monkeypatch, failure):
    monkeypatch.setattr('shantytown.tmux.sys.platform', 'darwin')

    def run(cmd, **kwargs):
        if cmd[0] == 'tmux':
            return subprocess.CompletedProcess(cmd, 0, '100 st-worker\n', '')
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(cmd, 2)
        if failure == 'missing':
            raise FileNotFoundError('pgrep')
        if failure == 'denied':
            return subprocess.CompletedProcess(cmd, 2, '', 'denied')
        return subprocess.CompletedProcess(cmd, 0,
            'oops' if failure == 'malformed' else '\n'.join(['101'] * 257), '')

    monkeypatch.setattr(subprocess, 'run', run)
    line = Tmux().cmdline('st-worker')
    assert line is None
    assert launchable.observed_posture('› ready', True, line) == launchable.UNKNOWN


@pytest.mark.parametrize('old_age,young_age', [('01:02', '00:59'), ('02:00:00', '59:59'),
                                             ('1-00:00:00', '23:59:59')])
def test_darwin_age_keeps_oldest_settings_pointer(monkeypatch, old_age, young_age):
    monkeypatch.setattr('shantytown.tmux.sys.platform', 'darwin')

    def run(cmd, **kwargs):
        if cmd[0] == 'tmux':
            return subprocess.CompletedProcess(cmd, 0, '100 st-worker\n', '')
        if cmd[0] == 'pgrep':
            return subprocess.CompletedProcess(cmd, 0, '101\n102\n', '')
        # Deliberately put the young transient first; row order is not age.
        return subprocess.CompletedProcess(cmd, 0,
            f'{young_age} 102 claude --settings /tmp/transient.json\n'
            f'{old_age} 101 claude --settings /tmp/actual.json\n', '')

    monkeypatch.setattr(subprocess, 'run', run)
    assert Tmux().cmdline('st-worker') == 'claude --settings /tmp/actual.json'


@pytest.mark.parametrize('stage', ['tmux', 'ps'])
@pytest.mark.parametrize('failure', ['denied', 'timeout', 'missing'])
def test_observation_failures_at_each_stage_are_unknown(monkeypatch, stage, failure):
    monkeypatch.setattr('shantytown.tmux.sys.platform', 'darwin')

    def run(cmd, **kwargs):
        if cmd[0] == stage:
            if failure == 'timeout':
                raise subprocess.TimeoutExpired(cmd, 2)
            if failure == 'missing':
                raise FileNotFoundError(cmd[0])
            return subprocess.CompletedProcess(cmd, 2, '', 'denied')
        return subprocess.CompletedProcess(cmd, 0,
            '100 st-worker\n' if cmd[0] == 'tmux' else '101\n', '')

    monkeypatch.setattr(subprocess, 'run', run)
    assert Tmux().cmdline('st-worker') is None
