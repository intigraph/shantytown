"""Opt-in Linux user-manager acceptance; only random private test sockets.

Run with SHANTY_TEST_SYSTEMD_TMUX=1 under the normal test guard. The first arm
reproduces server loss at oneshot cleanup; the second uses Tmux.new_session and
must survive the same cleanup. No fleet socket or live service is addressed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest


@pytest.mark.skipif(os.environ.get('SHANTY_TEST_SYSTEMD_TMUX') != '1',
                    reason='explicit isolated Linux user-manager acceptance only')
def test_fresh_server_survives_launcher_service_cleanup(tmp_path):
    assert sys.platform == 'linux'
    for name in ['tmux', 'systemd-run', 'systemctl']:
        assert shutil.which(name), f'{name} required for the opted-in control'
    subprocess.run(['systemctl', '--user', 'is-active', 'default.target'],
                   check=True, capture_output=True, timeout=10)
    source = str(Path(__file__).resolve().parents[1])
    key = uuid.uuid4().hex
    sockets = {arm: f'st-test-{key}-{arm}' for arm in ['control', 'fixed']}
    units = {arm: f'st-test-launcher-{key}-{arm}' for arm in sockets}
    tmux = shutil.which('tmux')
    evidence = {}
    try:
        for arm, socket in sockets.items():
            record = tmp_path / f'{arm}.json'
            program = r'''
import json,os,subprocess,sys
from pathlib import Path
from shantytown.tmux import Tmux
from shantytown import tmux_scope
socket,arm,record,tmux=sys.argv[1:]
class PrivateTmux(Tmux):
    def _cmd(self,*args):
        return [tmux,'-f','/dev/null','-L',self.socket,*args]
p=PrivateTmux(socket=socket)
assert not p.exists('isolated')
owner=tmux_scope.user_service(Path('/proc/self/cgroup').read_text(),os.getuid())
assert owner and owner.startswith('st-test-launcher-')
if arm=='control':
    subprocess.run(p._cmd('new-session','-d','-s','isolated'),check=True)
else:
    p.new_session('isolated')
pid=int(subprocess.check_output(p._cmd('display-message','-p','#{pid}'),text=True))
Path(record).write_text(json.dumps({'pid':pid,'launcher_unit':owner,
 'server_cgroup':Path(f'/proc/{pid}/cgroup').read_text()}))
'''
            argv = ['systemd-run', '--user', '--wait', '--pipe', '--collect',
                    '--property=Type=oneshot', '--property=KillMode=control-group',
                    f'--unit={units[arm]}', '--', '/usr/bin/env',
                    f'HOME={tmp_path}', f'PYTHONPATH={source}',
                    'PYTHONDONTWRITEBYTECODE=1', 'SHANTY_PANE_MEMORY=0',
                    'QUIPU_SERVER=http://127.0.0.1:0',
                    f'SHANTY_PANEMEM_LOG={tmp_path}/panemem.log',
                    sys.executable, '-c', program, socket, arm, str(record), tmux]
            result = subprocess.run(argv, capture_output=True, text=True, timeout=35)
            assert result.returncode == 0, result.stderr
            data = json.loads(record.read_text())
            alive = subprocess.run([tmux, '-L', socket, 'has-session', '-t', 'isolated'],
                                   capture_output=True, timeout=10).returncode == 0
            if arm == 'control':
                assert data['launcher_unit'] in data['server_cgroup']
                assert not alive, 'control did not reproduce service cleanup'
            else:
                assert data['launcher_unit'] not in data['server_cgroup']
                assert 'st-tmux-' in data['server_cgroup']
                assert alive, 'protected server died with its launcher'
            evidence[arm] = {**data, 'alive_after_service_exit': alive}
        print(json.dumps(evidence, sort_keys=True))
    finally:
        for socket in sockets.values():
            assert socket.startswith(f'st-test-{key}-')
            subprocess.run([tmux, '-L', socket, 'kill-server'],
                           capture_output=True, timeout=10)
        for unit in units.values():
            assert unit.startswith(f'st-test-launcher-{key}-')
            subprocess.run(['systemctl', '--user', 'stop', unit],
                           capture_output=True, timeout=10)
