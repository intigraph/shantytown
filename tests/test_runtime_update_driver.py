from types import SimpleNamespace

from shantytown import cycle_advice as ca, notify, triage
from shantytown.protocols import Agent


def test_idle_shallow_update_prompt_is_deduped_and_replacement_only(tmp_path, monkeypatch):
    cards=[Agent(name=n,pane=n) for n in ("idle","busy","shell","unknown-shell")]
    states={
        "idle":notify.PaneRead(triage.IDLE,20,shells=0),
        "busy":notify.PaneRead(triage.BUSY,None,shells=0),
        "shell":notify.PaneRead(triage.IDLE,20,shells=1),
        "unknown-shell":notify.PaneRead(triage.IDLE,20,shells=None)}
    monkeypatch.setattr(notify,"agent_states",lambda *args:states)
    sent=[];logs=[];called=[]
    def advise(name,depth):
        called.append(name)
        return ca.Advice(ca.CYCLE,"Claude Code running 2.1.317, installed 2.1.318",
            restart_required=True,runtime_version_key="exact:2.1.317->2.1.318")
    driver=notify.CycleDriver(tmp_path,None,None,
        push=lambda reg,panes,name,text:sent.append((name,text)) or name,
        wiring=lambda name:SimpleNamespace(directions=["send","haul"]),
        advise=advise,log=logs.append)
    assert driver.sweep(cards,None)==["idle"]
    assert driver.sweep(cards,None)==[]
    assert called==["idle","idle"]
    assert len(sent)==1 and sent[0][0]=="idle"
    assert "--self --no-in-place --checkpoint-file" in sent[0][1]
    assert "CONTEXT HIGH" not in sent[0][1]
    assert "running 2.1.317, installed 2.1.318" in logs[0]
    assert not (tmp_path/"notify/cycle-requests.json").exists()


def test_foreign_and_failed_delivery_do_not_spend_update_prompt(tmp_path, monkeypatch):
    cards=[Agent(name="reader",pane="p")]
    monkeypatch.setattr(notify,"agent_states",lambda *args:{"reader":notify.PaneRead(triage.IDLE,10,shells=0)})
    advice=ca.Advice(ca.CYCLE,"update",restart_required=True,runtime_version_key="session:old->new")
    driver=notify.CycleDriver(tmp_path,None,None,wiring=lambda name:None,
        advise=lambda *args:advice,push=lambda *args:(_ for _ in ()).throw(AssertionError("foreign pane")))
    assert driver.sweep(cards,None)==[]
    calls=[]
    driver._wiring_fn=lambda name:SimpleNamespace(directions=["send"])
    driver._push=lambda *args:calls.append(args) or (None if len(calls)==1 else "reader")
    assert driver.sweep(cards,None)==[]
    assert driver.sweep(cards,None)==["reader"]
    assert driver.sweep(cards,None)==[]
    assert len(calls)==2


def test_pending_or_unknown_request_cannot_receive_competing_prompt(tmp_path, monkeypatch):
    from shantytown.cycle import Requests
    cards=[Agent(name="reader",pane="p")]
    monkeypatch.setattr(notify,"agent_states",lambda *args:{"reader":notify.PaneRead(triage.IDLE,10,shells=0)})
    advice=ca.Advice(ca.CYCLE,"update",restart_required=True,runtime_version_key="exact:old->new")
    sent=[]
    driver=notify.CycleDriver(tmp_path,None,None,wiring=lambda name:SimpleNamespace(directions=["send"]),
        advise=lambda *args:advice,push=lambda *args:sent.append(args) or "reader")
    requests=Requests(tmp_path);requests.request("reader","checkpoint",no_in_place=True)
    assert driver.sweep(cards,None)==[] and not sent
    requests.path.write_text("malformed")
    assert driver.sweep(cards,None)==[] and not sent
    requests.path.unlink()
    assert driver.sweep(cards,None)==["reader"]


def test_pane_becoming_busy_during_version_lookup_gets_no_prompt(tmp_path, monkeypatch):
    calls=[];sent=[]
    def states(*args):
        calls.append(True)
        return {"reader":notify.PaneRead(triage.IDLE if len(calls)==1 else triage.BUSY,10,shells=0)}
    monkeypatch.setattr(notify,"agent_states",states)
    advice=ca.Advice(ca.CYCLE,"update",restart_required=True,runtime_version_key="exact:old->new")
    driver=notify.CycleDriver(tmp_path,None,None,wiring=lambda name:SimpleNamespace(directions=["send"]),
        advise=lambda *args:advice,push=lambda *args:sent.append(args) or "reader")
    assert driver.sweep([Agent(name="reader",pane="p")],None)==[]
    assert not sent and len(calls)==2
