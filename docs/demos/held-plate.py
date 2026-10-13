import json,subprocess
from shantytown.sd import SdTracker
from shantytown import br
tracker=SdTracker(quipu='https://example.test',prefix='demo')
rows=[dict(id='held',title='Current task',assignee='worker',status='in_progress',priority=1)] + [dict(id=f'message-{i}',title='inbox: Notification',assignee='worker',status='open',priority=2) for i in range(200)]
calls=[]
def run(*args):
 status=args[args.index('--status')+1] if '--status' in args else None
 selected=[r for r in rows if status is None or r['status']==status] if args[0]=='list' else rows[1:]
 calls.append((args[0],status,len(selected)))
 return subprocess.CompletedProcess(args,0,json.dumps(dict(issues=selected,total=len(selected),has_more=False)),'')
tracker._bd=run
br.name_the_blocker=lambda _,item:item
print('Input: one in_progress task and 200 unread notifications.')
print('Selected plate:',br.plate(tracker,'worker').id)
for command,status,count in calls:print(f'  sd {command}, status={status}: {count} rows')
