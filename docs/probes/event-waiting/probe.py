"""Private stop fixture: real waiting/idle filter, controlled liveness and pool."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from shantytown import feed_check, runtime, session_budget, stop_policy
from shantytown.files import FilesRegistry
from shantytown.protocols import Agent
from shantytown.tmux import NullPanes


def count(minutes):
    with tempfile.TemporaryDirectory(prefix='waiting-fixture-') as directory:
        root = Path(directory)
        (root / 'shantytown.toml').write_text('[env]\nSHANTY_BACKEND="files"\n')
        (root / 'items').mkdir()
        if minutes is not None:
            row = dict(id='wait', title='waiting for CI', assignee='worker',
                       status='deferred', labels=['blocked:external'], priority=2,
                       defer_until=(datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat())
            (root / 'items' / 'wait.json').write_text(json.dumps(row))
        reg = FilesRegistry(root / 'crew')
        reg.set(Agent(name='worker', role='worker', pane='p'))
        panes = NullPanes(live={'p'}, screen='> \n? for shortcuts')
        program = runtime.ClaudeRuntime(panes, lambda *a: None)
        with patch.object(feed_check, 'st_launched_agents', return_value=None), \
             patch.object(feed_check, 'dark_agents', return_value=set()), \
             patch.object(runtime, 'live_wiring', return_value=SimpleNamespace(directions={'send'})), \
             patch.object(session_budget, 'at_ceiling', return_value=None), \
             patch.object(feed_check, 'queue_state', return_value=([dict(id='task', title='do next', status='open', priority=2)], [])):
            prompts = 0
            for _ in range(10):
                free, ready, _ = feed_check.gate_inputs(root, reg, panes, program, admits=lambda item: '')
                prompts += stop_policy.decide(stop_policy.Inputs(me='admin', role='administrator',
                                              free_feedable=free, dispatchable=len(ready))).block
            return dict(free=free, prompt_count_per_10_turns=prompts)


print(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(), waiting=count(120),
                     near_control=count(15), idle_control=count(None),
                     unsuitable_candidates=feed_check.dispatchable({'worker'}, [
                         dict(id='epic', issue_type='epic', title='umbrella'),
                         dict(id='parked', title='parked', labels=['parked:by-design']),
                         dict(id='owned', title='owned', assignee='other'),
                         dict(id='human', title='human', labels=['needs-stiwi'])])), indent=2))
