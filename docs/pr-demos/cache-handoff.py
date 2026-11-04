"""Offline base/candidate comparison; synthetic work, no pane or board calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
from dataclasses import asdict

from shantytown import cycle_advice as after

BASE='7923c5cfc68057406a39c4aee6479f6e509954bf'
before=types.ModuleType('shantytown._demo_before')
before.__package__='shantytown'
sys.modules[before.__name__]=before
source=subprocess.run(['git','show',BASE+':shantytown/cycle_advice.py'],check=True,capture_output=True,text=True).stdout
exec(compile(source,'base-cycle-advice.py','exec'),before.__dict__)

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    transcript=root/'codex.jsonl'
    rows=[{'timestamp':'2026-11-04T09:00:00Z','type':'turn_context','payload':{'model':'gpt-6.1-sol'}},
          {'timestamp':'2026-11-04T09:01:00Z','type':'event_msg','payload':{'type':'token_count',
           'info':{'last_token_usage':{'input_tokens':12000,'cached_input_tokens':11000,'cache_write_input_tokens':1000}}}}]
    transcript.write_text(''.join(json.dumps(row)+'\n' for row in rows))
    print('BEFORE:',json.dumps(asdict(before.read_cache(transcript)),sort_keys=True))
    cache=after.read_cache(transcript)
    print('AFTER:',json.dumps(asdict(cache),sort_keys=True))
    prior=dict(id='old-work',labels=['repo:example'],description='src/old.py')
    next_work=dict(id='next-work',labels=['repo:example'],description='src/new.py')
    seed=after.Situation('demo',80,400,now=cache.last_at)
    first=after.handoff_preview(root,prior,seed,after.Policy())
    print('COLD START:',first['notice'])
    after.record_handoff(root,'demo',first)  # seed a prior-handoff fixture, not a live dispatch
    for idle in [10,1801]:
        sit=after.Situation('demo',80,400,cache=cache,now=cache.last_at+idle)
        preview=after.handoff_preview(root,next_work,sit,after.Policy())
        print('NEXT:',preview['notice'])
    print('No live dispatch, lifecycle action, tracker write or model call.')
