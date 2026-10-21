import hashlib,json,os,sys,tempfile,subprocess
from pathlib import Path
import shantytown.plate_capacity as capacity
from shantytown.files import FilesTracker
from shantytown.producer_capacity import run

with tempfile.TemporaryDirectory() as home:
 previous_home=os.environ.get("HOME")
 os.environ["HOME"]=home
 try:
  rows=[]
  for count in (9,10):
   for mode in ('tracker','sdk'):
    with tempfile.TemporaryDirectory() as root:
     tracker=FilesTracker(Path(root)/'items')
     for n in range(count): tracker.create(f'work{n}',assignee='worker')
     alarm=tracker.create('Recurring alarm: detector',assignee='worker',labels=['recurring-alarm'])
     before=tracker._path(alarm.id).read_bytes();writes=[];raw_update=tracker.update
     def update(item_id,**fields):
      writes.append(item_id);raw_update(item_id,**fields)
     tracker.update=update;refused=False
     try:
      if mode=='tracker':
       capacity.guard_producers(tracker,lambda *args:None)
       tracker.update(alarm.id,title='Implementation',labels=[])
      else:
       def execute(args):
        tracker.update(alarm.id,title='Implementation',labels=[])
        return subprocess.CompletedProcess(args,0,json.dumps({'id':alarm.id}),'')
       run(['update',alarm.id,'--title','Implementation','--labels',''],tracker,execute,lambda *args:None)
     except capacity.PlateFull: refused=True
     row=dict(mode=mode,before_real=count,after_real=capacity.size(tracker,'worker'),refused=refused,writes=len(writes),unchanged=tracker._path(alarm.id).read_bytes()==before)
     expected_refusal=sys.argv[1]=='fixed' and count==10
     assert refused==expected_refusal,row
     assert row['after_real']==(count if expected_refusal else count+1),row
     assert row['writes']==(0 if expected_refusal else 1),row
     assert not expected_refusal or row['unchanged'],row
     rows.append(row)
  print(json.dumps({'source_sha256':hashlib.sha256(Path(capacity.__file__).read_bytes()).hexdigest(),'expected':sys.argv[1],'results':rows},indent=2))
 finally:
  if previous_home is None: os.environ.pop("HOME",None)
  else: os.environ["HOME"]=previous_home
