import sys,json
sys.path.insert(0, sys.argv[1])
from shantytown import ceiling_transfer as ct, __version__
from shantytown.dispatch import TriageRefused
from shantytown.triage import Decision, Action
moves=[ct.Move(f"fixture-{i}","holder","busy","session ceiling","fixture") for i in range(5)]
moves.insert(2,ct.Move("control","holder","available","session ceiling","fixture"))
calls=[];comments=[];events=[];logs=[]
def dispatch(item,to,note):
 calls.append((item,to))
 if to=='busy':raise TriageRefused(Decision(Action.REFUSE,'in-flight work',{'busy':True}))
out=ct.apply(moves,dispatch=dispatch,comment=lambda *c:comments.append(c),emit=events.append,log=logs.append)
next_calls=[]
next_out=ct.apply([moves[0]],dispatch=lambda *c:next_calls.append(c),comment=lambda *c:None,emit=lambda e:None,log=lambda m:None)
print(json.dumps({'version':__version__,'busy_attempts':sum(t=='busy' for _,t in calls),'available_attempts':sum(t=='available' for _,t in calls),'outcomes':len(out),'moved':[x.move.item for x in out if x.moved],'commented':[x[0] for x in comments],'event_items':[x['item'] for x in events],'next_pass_attempts':len(next_calls),'next_pass_moved':next_out[0].moved},indent=2))
