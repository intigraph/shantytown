"""Offline library metadata demonstration; no terminal connection or keystrokes."""
import json
import subprocess
from types import SimpleNamespace
from shantytown import triage, input_observation

screen = '› synthetic ambiguous fixture'
print('Same offline ambiguous capture; existing classifier versus metadata wrapper.')
print('Before:', json.dumps(dict(state=triage.input_state(screen))))
read = SimpleNamespace(capture=lambda *a, **kw: screen)
result = input_observation.capture(read, 'fixture', wall_clock=lambda: 1000, monotonic=lambda: 2)
print('After:', json.dumps({k: result[k] for k in ('state', 'reason', 'observed_at', 'elapsed_seconds')}))
assert result['state'] == triage.INPUT_UNKNOWN

def fail(*a, **kw):
    raise subprocess.TimeoutExpired('synthetic private detail', 5)
result = input_observation.capture(SimpleNamespace(capture=fail), 'fixture',
                                   wall_clock=lambda: 1000, monotonic=lambda: 2)
print('Timeout:', json.dumps({k: result[k] for k in ('state', 'reason', 'observed_at')}))
assert result['state'] == triage.INPUT_UNKNOWN and result['reason'] == 'capture-timeout'
assert 'synthetic private detail' not in json.dumps(result)
print('UNKNOWN retained; no screen/exception text, submit, clear, or live-pane action.')
