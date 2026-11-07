"""Isolated source probe: no Git, network, panes or live fleet mutations."""
from inspect import signature
from types import SimpleNamespace
from pathlib import Path
from shantytown import cli

clock, refreshed = [0.0], []
cli.time.monotonic = lambda: clock[0]
cli.agent_worktrees = lambda name: [Path('first'), Path('second'), Path('third')]


def refresh(path, **kwargs):
    refreshed.append((str(path), kwargs.get('retire_topics', True)))
    clock[0] += 31


cli._refresh_worktree = refresh
kwargs = ({'deadline': 30.0}
          if 'deadline' in signature(cli._refresh_agent_worktrees).parameters else {})
result = cli._refresh_agent_worktrees(SimpleNamespace(), SimpleNamespace(name='worker'), **kwargs)
print('Refreshed trees and remote-retirement setting:', refreshed)
print('Warnings:', result)
print('Synthetic elapsed seconds:', clock[0])
