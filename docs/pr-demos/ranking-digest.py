"""Replay a five-worker, 34-READY digest without live tracker or notification I/O.

python3 ranking-digest.py --source /path/to/source-checkout
"""
import argparse
import contextlib
import io
from pathlib import Path
import json
import sys
import tempfile
import time
from types import SimpleNamespace

ap=argparse.ArgumentParser()
ap.add_argument("--source",required=True)
a=ap.parse_args()
sys.path.insert(0,str(Path(a.source).resolve()))
from shantytown import ranking_check as ranking
from shantytown.answer import Answer
from shantytown.protocols import Agent

cards=[Agent(name=f"worker{i}",pane=f"worker{i}") for i in range(5)]
owned=[dict(id=f"active-{i}",title="work",status="in_progress",priority=2,
            assignee=c.name,labels=[]) for i,c in enumerate(cards)]
ready=[dict(id=f"unowned-{i:02}",title="work",status="open",priority=1,
            rank=str(34-i),labels=[]) for i in range(34)]
rows=owned+ready
reg=SimpleNamespace(all=lambda:Answer.complete_read(cards,how="isolated fixture"))
panes=SimpleNamespace(exists=lambda p:True)
clock=[1000]
time.time=lambda:clock[0]
text,_=ranking.digest(ready,rows,cards,{c.name for c in cards},counts="counts")
print(text)
with tempfile.TemporaryDirectory(prefix="ranking-digest-") as tmp:
    logs=[];pushes=[]
    for seconds in range(0,3600,600):
        clock[0]=1000+seconds
        with contextlib.redirect_stdout(io.StringIO()):
            ranking.sweep(Path(tmp),reg,panes,snapshot=lambda:(ready,rows),
                counts_reader=lambda root:"counts",log=logs.append,
                push=lambda *args:pushes.append(args) or True)
    print(json.dumps(dict(digest_utf8_bytes=len(text.encode()),
        digest_logs_in_six_10minute_sweeps=len(logs),administrator_pushes=len(pushes))))
    clock[0]=4600
    with contextlib.redirect_stdout(io.StringIO()):
        ranking.sweep(Path(tmp),reg,panes,snapshot=lambda:(ready,rows),
            counts_reader=lambda root:"counts",log=logs.append,push=lambda *args:True)
    print(json.dumps(dict(total_digest_logs_after_hourly_reminder=len(logs))))
