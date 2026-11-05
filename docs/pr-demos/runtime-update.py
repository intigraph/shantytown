"""Isolated running317/installed318 update advice and idle-prompt replay.

python3 runtime-update.py --source /path/to/source-checkout
No live pane, tracker, provider, updater or cycle executor is used.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

ap=argparse.ArgumentParser();ap.add_argument("--source",required=True);a=ap.parse_args()
sys.path.insert(0,str(Path(a.source).resolve()))
with tempfile.TemporaryDirectory(prefix="runtime-update-") as tmp:
    root=Path(tmp);home=root/"home";home.mkdir()
    os.environ["HOME"]=str(home)
    os.environ["XDG_CONFIG_HOME"]=str(home/".config")
    os.environ["XDG_CACHE_HOME"]=str(home/".cache")
    clock=[1000];time.time=lambda:clock[0]
    binary=root/"bin/claude";binary.parent.mkdir()
    binary.write_text('#!/bin/sh\nprintf "%s\\n" "2.1.318 (Claude Code)"\n');binary.chmod(0o755)
    os.environ["PATH"]=str(binary.parent)+os.pathsep+os.environ.get("PATH","")
    from shantytown import cli,notify,stats,triage
    from shantytown.answer import Answer
    from shantytown.files import FilesRegistry
    from shantytown.launched import FilesLaunches
    workspace=root/"workspace";workspace.mkdir()
    (root/"crew").mkdir()
    (root/"crew/demo.json").write_text(json.dumps(dict(role="worker",pane="demo",harness="claude",workspace=str(workspace))))
    settings=root/"settings.json";settings.write_text('{}')
    stamps=FilesLaunches(root/"launched");stamps.record("demo",settings)
    os.utime(root/"launched/demo.json",(900,900))
    project=home/".claude/projects"/stats._claude_project_dir(str(workspace));project.mkdir(parents=True)
    def native(session,version,at):
        (project/(session+'.jsonl')).write_text(json.dumps(dict(type="api-request",sessionId=session,
            version=version,timestamp=f"1970-01-01T00:{at//60:02}:{at%60:02}Z"))+'\n')
        db=stats._db(root)
        db.execute("INSERT INTO events(ts,agent,kind,session) VALUES(?,?,?,?)",(at,"demo","stop",session))
        db.commit();db.close()
    native("old-session","2.1.317",1000)
    reg=FilesRegistry(root/"crew");card=reg.get("demo")
    advisor=cli._cycle_advisor(SimpleNamespace(root=root))
    advice=advisor("demo",20)
    print(json.dumps(dict(running="2.1.317",installed="2.1.318",depth_k=20,
        advice=advice.decision if advice else "no preference",
        restart_required=getattr(advice,"restart_required",False))))
    # The idle observation and delivery sink are synthetic. The actual
    # CycleDriver/CLI advisor and request ledger behavior are exercised.
    state=[triage.IDLE]
    notify.agent_states=lambda *args:{"demo":notify.PaneRead(state[0],20,shells=0)}
    sent=[]
    driver=notify.CycleDriver(root,reg,None,advise=advisor,
        wiring=lambda name:SimpleNamespace(directions=["send","haul"]),
        push=lambda reg,panes,name,message:sent.append(message) or name)
    print(json.dumps(dict(first_idle_prompt=driver.sweep([card],None),
        repeat_prompt=driver.sweep([card],None),
        replacement_flag=bool(sent and "--no-in-place" in sent[0]))))
    state[0]=triage.BUSY
    print(json.dumps(dict(busy_prompt=driver.sweep([card],None))))
    # Simulated fresh-session records, not an executed process relaunch.
    clock[0]=1200;native("fresh-session","2.1.318",1200)
    os.utime(root/"launched/demo.json",(1100,1100))
    state[0]=triage.IDLE
    advice=advisor("demo",20)
    print(json.dumps(dict(simulated_fresh_running="2.1.318",
        advice=advice.decision if advice else "no preference",
        fresh_prompt=driver.sweep([card],None))))
    print(json.dumps(dict(cycle_request_created=(root/"notify/cycle-requests.json").exists())))
