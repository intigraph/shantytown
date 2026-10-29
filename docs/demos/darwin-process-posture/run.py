"""Synthetic Darwin process tree; run from either source revision.

No live process arguments or environment are collected by this demo.
"""
import subprocess
import sys
from unittest.mock import patch

from shantytown import launchable
from shantytown.tmux import Tmux


def probe(bypass=True, denied=False):
    def run(command, **kwargs):
        if command[0] == 'tmux':
            return subprocess.CompletedProcess(command, 0, '100 demo-pane\n', '')
        if denied:
            return subprocess.CompletedProcess(command, 2, '', 'permission denied')
        if command[0] == 'pgrep':
            # BSD pgrep hides ancestors without -a, including this agent.
            visible = '-a' in command
            return subprocess.CompletedProcess(command, 0 if visible else 1,
                                               '101\n' if visible else '', '')
        if '--ppid' in command or 'etimes=,pid=,args=' in command:
            return subprocess.CompletedProcess(command, 1, '', 'unsupported GNU ps options')
        flag = ' --dangerously-bypass-approvals-and-sandbox' if bypass else ''
        return subprocess.CompletedProcess(command, 0,
            f'10:00 100 -zsh\n09:59 101 codex{flag}\n', '')

    with patch.object(sys, 'platform', 'darwin'), patch.object(subprocess, 'run', run):
        line = Tmux().cmdline('demo-pane')
    return {'readable': line is not None,
            'posture': launchable.observed_posture('› ready', True, line)}


for name, options in [('bypass launch', {}), ('manual launch', {'bypass': False}),
                       ('denied observation', {'denied': True})]:
    print(name, probe(**options))
