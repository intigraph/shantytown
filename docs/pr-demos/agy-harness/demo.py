"""Offline library demonstration. No agent, provider request or credential access."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, sys.argv[1])
from shantytown.harness import get, UnknownHarness
from shantytown.protocols import Agent

print('Input: worker card selects agy; no live process or model request.')
try:
    program=get('agy')
except UnknownHarness:
    print('Result: agy unsupported; launch refused.')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='agy-demo-') as temporary:
    root=Path(temporary)
    card=Agent('demo',harness='agy',workspace='/workspace/demo',model='gemini-3.8-flash-low')
    config=root/'settings.json'
    config.write_text(program.render(program.settings('worker',root)))
    launch=program.launch(card,str(config),root)
    print('Result: adapter =',program.name)
    print('Sandbox carried =','--sandbox' in launch)
    print('Paid credit fallback =',json.loads(config.read_text())['useG1Credits'])
    print('Stop routing =',sorted(program.read_stop_directions(config.read_text())))
    from shantytown.runtime import live_wiring, require_capability, CapabilityError
    print('Missing native receipt remains UNKNOWN =',live_wiring('demo',lambda _:launch) is None)
    try:
        require_capability(program,Agent('demo',role='lead'))
        raise AssertionError('unproved lead admission')
    except CapabilityError:
        print('Unproved lead admission = REFUSED')
    from shantytown.agy_usage import AgyUsageReader
    fixture={'status':'SUCCESS','num_turns':0,'command':{'name':'usage','data':{'groups':[
        {'name':'General','buckets':[{'window':'weekly','remaining_fraction':1,'reset_time':'2030-01-01T00:00:00Z'}]},
        {'name':'Argon','buckets':[{'window':'weekly','remaining_fraction':0,'reset_time':'2030-01-01T00:00:00Z'}]}]}}}
    run=lambda *a,**k:SimpleNamespace(returncode=0,stdout=json.dumps(fixture))
    print('Quota FIXTURE: general used =',AgyUsageReader('seven_day','General',run=run).read().pct)
    print('Quota FIXTURE: Argon used =',AgyUsageReader('seven_day','Argon',run=run).read().pct)
    print('Unspecified quota group remains UNKNOWN =',not AgyUsageReader('seven_day',None,run=run).read().ok)
