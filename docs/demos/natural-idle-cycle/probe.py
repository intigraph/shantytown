"""Isolated library fixture; no journal, pane, cycle or tracker mutation."""
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

if len(sys.argv) == 1:
    for label, source in [('base 165e24e7', os.environ['DEMO_BASE_SOURCE']),
                          ('candidate source', os.getcwd())]:
        result = subprocess.run([sys.executable, __file__, 'child'],
                                env=dict(os.environ, PYTHONPATH=source),
                                capture_output=True, text=True, check=True)
        print(label)
        print(result.stdout, end='')
    raise SystemExit(0)

from shantytown import resume_events, triage
now = datetime(2026, 11, 10, 10, tzinfo=timezone.utc)
identifier, item = 'natural-idle-cycle-v1', 'aegis-zl7jwm'
if importlib.util.find_spec('shantytown.resume_idle_cycle') is None:
    for trigger in ('automatic idle success', 'refused cycle', 'manual cycle', 'foreign journal unit'):
        result = resume_events.evaluate(identifier, item, now)
        assert result.state == 'UNKNOWN'
        print(f'{trigger}: registered=false receipt=false verdict={result.state}')
else:
    from shantytown import resume_idle_cycle as idle
    binding = resume_events.binding_for(identifier, item)
    request = {'auto': True, 'requested_at': now.timestamp() - 60, 'checkpoint_bead': 'project-checkpoint'}
    read = SimpleNamespace(state=triage.IDLE, depth_k=500)
    for trigger, auto, result, unit in [
            ('automatic idle success', True, 0, idle.UNIT),
            ('refused cycle', True, 2, idle.UNIT),
            ('manual cycle', False, 0, idle.UNIT),
            ('foreign journal unit', True, 0, 'unrelated.service')]:
        message = idle.receipt(request | {'auto': auto}, 'worker', read, result)
        rows = [] if message is None else [{
            'MESSAGE': message, '_SYSTEMD_USER_UNIT': unit, '_UID': '1000',
            '_BOOT_ID': 'a' * 32, '_SYSTEMD_INVOCATION_ID': 'b' * 32,
            '__CURSOR': 'fixture-native-cursor',
            '__REALTIME_TIMESTAMP': str(int((now.timestamp() - 1) * 1e6))}]
        verdict = idle.decide(b'\n'.join(json.dumps(r).encode() for r in rows),
                              binding, now, uid=1000, boot='a' * 32)
        assert verdict.state == ('MET' if trigger == 'automatic idle success' else 'UNKNOWN')
        print(f'{trigger}: registered=true receipt={str(message is not None).lower()} verdict={verdict.state}')
