"""Synthetic source fixture; no production board, pane, or credentials."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from shantytown.files import FilesTracker
from shantytown import plate_capacity as candidate

BASE='1434b3df1c80c92055ad8d6a470c15b62d81b54e'
old=types.ModuleType('shantytown._capacity_before')
old.__package__='shantytown'
exec(subprocess.check_output(['git','show',BASE+':shantytown/plate_capacity.py'],text=True),old.__dict__)
rows=[dict(id=str(i),title='implementation task',assignee='worker',status='open') for i in range(2)]
rows += [dict(id=str(i+2),title='Recurring alarm: fixture',labels=['recurring-alarm'],assignee='worker',status='open') for i in range(8)]
rows += [dict(id=str(i+10),title='inbox: fixture',assignee='worker',status='open') for i in range(7)]
print('SOURCE fixture: baseline',BASE)
print('candidate module sha256',hashlib.sha256(Path(candidate.__file__).read_bytes()).hexdigest())
print('SAME input: 17 records = 2 implementation tasks + 8 alarms + 7 messages')
print('BEFORE capacity count:',sum(old.active(row,'worker') for row in rows))
print('AFTER capacity count:',sum(candidate.active(row,'worker') for row in rows))
assert sum(candidate.active(row,'worker') for row in rows)==2
with tempfile.TemporaryDirectory(prefix='capacity-demo-') as directory:
    prior=os.environ.get('HOME')
    try:
        os.environ['HOME']=directory
        tracker=FilesTracker(Path(directory)/'items')
        for n in range(10):tracker.create(f'implementation {n}',assignee='worker')
        notices=[]
        candidate.guard_producers(tracker,lambda *args:notices.append(args))
        overflow=tracker.create('overflow',assignee='worker')
        assert overflow.assignee is None and len(notices)==1
        print('10 real tasks: overflow preserved in pool; one lead-notice callback')
        message=tracker.create('inbox: delivery',assignee='worker')
        alarm=tracker.create('Recurring alarm: delivery',assignee='worker')
        assert message.assignee==alarm.assignee=='worker'
        print('Alarm + inbox delivery: delivered; real count remains',candidate.size(tracker,'worker'))
    finally:
        if prior is None:os.environ.pop('HOME',None)
        else:os.environ['HOME']=prior
print('FIXTURE ONLY: file store/temporary HOME; no live assignment or installed recovery claim')
