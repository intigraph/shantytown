"""Run the same synthetic queue rows on base and candidate package trees."""
import json
import os
import subprocess
import sys

probe = '''
import json
from shantytown.ask_visibility import is_ask
from shantytown.plate_capacity import real_work
from shantytown.feed_check import hauls
from shantytown.stop_event import _assigned_to
ask = dict(id='test-ask', title='Choose a color', issue_type='ask',
           assignee='worker', status='open', priority=1, labels=[])
work = dict(ask, id='test-work', issue_type='task', title='Implement the choice')
print(json.dumps(dict(ask=is_ask(ask), work_capacity=real_work(ask),
    haul=hauls([ask, work]), plate_candidates=[r['id'] for r in _assigned_to('worker', [ask, work])]), sort_keys=True))
'''
for label, root in [('before', os.environ['DEMO_BEFORE']), ('after', os.environ['DEMO_AFTER'])]:
    env = dict(os.environ, PYTHONPATH=root)
    got = subprocess.run([sys.executable, '-c', probe], cwd=root, env=env,
                         text=True, capture_output=True, check=True)
    result = json.loads(got.stdout)
    print(label + ': ' + json.dumps(result, sort_keys=True))
    if label == 'before':
        assert result['work_capacity'] and 'test-ask' in result['plate_candidates']
    else:
        assert result['ask'] and not result['work_capacity']
        assert result['haul'] == {'worker': ['test-work']}
        assert result['plate_candidates'] == ['test-work']
