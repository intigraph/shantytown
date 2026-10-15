from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import pytest
from shantytown import feed_check, runtime, session_budget, stop_policy
from shantytown.files import FilesRegistry
from shantytown.protocols import Agent
from shantytown.tmux import NullPanes

now = datetime(2026, 10, 15, 17, 35, tzinfo=timezone.utc)
ids = [str(index) for index in range(8)]
rows = [{'id':'fixture-'+identifier,'title':'source acceptance','status':'deferred',
         'assignee':'worker','priority':2,'labels':[],
         'defer_until':(now+timedelta(minutes=10)).isoformat()} for identifier in ids]
with TemporaryDirectory(prefix='busy-wait-probe-') as directory, pytest.MonkeyPatch.context() as mp:
    root = Path(directory)
    (root/'shantytown.toml').write_text('[env]\nSHANTY_BACKEND=\"files\"\n')
    items=root/'items'
    items.mkdir()
    for value in rows:
        (items/(value['id']+'.json')).write_text(json.dumps(value))
    reg = FilesRegistry(root/'crew')
    reg.set(Agent(name='worker', role='worker', pane='p'))
    panes = NullPanes(live={'p'}, screen='> \n? for shortcuts')
    mp.setattr(feed_check,'st_launched_agents',lambda _:None)
    mp.setattr(feed_check,'dark_agents',lambda:set())
    mp.setattr(runtime,'live_wiring',lambda *a:SimpleNamespace(directions={'send'}))
    mp.setattr(session_budget,'at_ceiling',lambda *a:None)
    mp.setattr(feed_check,'queue_state',lambda *a,**k:(
        [{'id':'pool-1','title':'new work','status':'open','priority':2}],[]))
    if importlib.util.find_spec('shantytown.busy_wait') is not None:
        from shantytown import busy_wait
        mp.setattr(busy_wait,'utc_now',lambda:now)
    program=runtime.ClaudeRuntime(panes, lambda *a: None)
    false_blocks = 0
    for index in range(8):
        free,ready,_=feed_check.gate_inputs(root,reg,panes,program,admits=lambda *a:'')
        held=stop_policy.decide(stop_policy.Inputs(
            me='coordinator',role='administrator',free_feedable=free,dispatchable=ready))
        false_blocks += held.block
    print(json.dumps({'fixture_kind':'eight modeled observations, not historical replay',
                      'short_deferred_rows':len(rows), 'observations':8,
                      'false_rule_zero_blocks':false_blocks,'free':free},indent=2))
    for path in items.glob('*.json'):
        path.unlink()
    rows.clear()
    free,ready,_=feed_check.gate_inputs(root,reg,panes,program,admits=lambda *a:'')
    control=stop_policy.decide(stop_policy.Inputs(
        me='coordinator',role='administrator',free_feedable=free,dispatchable=ready))
    print(json.dumps({'empty_plate_positive_control_blocks':control.block}))
