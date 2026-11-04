"""Bound ranking output while retaining the P0-only notification contract."""
from types import SimpleNamespace
import time

from shantytown import ranking_check as ranking
from shantytown.answer import Answer
from shantytown.protocols import Agent


def scenario():
    cards = [Agent(name=f"worker{i}", pane=f"worker{i}") for i in range(5)]
    owned = [dict(id=f"active-{i}", title="work", status="in_progress", priority=2,
                  assignee=c.name, labels=[]) for i,c in enumerate(cards)]
    ready = [dict(id=f"unowned-{i:02}", title="work", status="open", priority=1,
                  rank=str(34-i), labels=[]) for i in range(34)]
    return cards, ready, owned + ready


def test_compact_workers_and_single_top_five_by_priority_rank():
    cards,ready,rows=scenario()
    text,actionable=ranking.digest(ready,rows,cards,{c.name for c in cards},counts="counts")
    assert not actionable
    assert len(text.encode()) < 650
    for c in cards:
        assert text.count(c.name+":") == 1
        assert f"{c.name}: active-" in text
    assert "34 unowned P1" in text
    assert "unowned-00" not in text, "rank must select the displayed top five"
    assert text.count("unowned-33") == 1
    assert "+29 more" in text
    assert text.index("unowned-33") < text.index("unowned-32")


def test_unchanged_digest_log_suppressed_hourly_but_change_logs_now(tmp_path, monkeypatch):
    cards,ready,rows=scenario()
    reg=SimpleNamespace(all=lambda:Answer.complete_read(cards,how="fixture"))
    panes=SimpleNamespace(exists=lambda p:True)
    logs=[];pushes=[];clock=[1000]
    monkeypatch.setattr(time,"time",lambda:clock[0])
    def sweep():
        return ranking.sweep(tmp_path,reg,panes,snapshot=lambda:(ready,rows),
            counts_reader=lambda root:"counts",log=logs.append,
            push=lambda *a:pushes.append(a) or True)
    for offset in range(0,3600,600):
        clock[0]=1000+offset
        assert sweep()==[]
    assert len(logs)==1
    assert not pushes, "P1 mismatches must not be reintroduced as pages"
    clock[0]=4600
    sweep()
    assert len(logs)==2
    ready.pop()
    sweep()
    assert len(logs)==3


def test_failed_p0_push_retries_despite_log_suppression(tmp_path, monkeypatch):
    cards,ready,rows=scenario()
    ready[0]["priority"]=0
    reg=SimpleNamespace(all=lambda:Answer.complete_read(cards,how="fixture"))
    panes=SimpleNamespace(exists=lambda p:True)
    logs=[];pushes=[]
    monkeypatch.setattr(time,"time",lambda:1000)
    def push(*args):
        pushes.append(args)
        return len(pushes)>1
    args=dict(snapshot=lambda:(ready,rows),counts_reader=lambda root:"counts",log=logs.append,push=push)
    assert ranking.sweep(tmp_path,reg,panes,**args)==[]
    assert ranking.sweep(tmp_path,reg,panes,**args)==["fleet"]
    assert ranking.sweep(tmp_path,reg,panes,**args)==[]
    assert len(pushes)==2 and len(logs)==1


def test_nonready_p0_and_mixed_priority_summary_remain_honest():
    cards,ready,rows=scenario()
    ready[0]["priority"]=0
    rows.append(dict(id="deferred-p0",title="work",status="deferred",priority=0,labels=[]))
    text,actionable=ranking.digest(ready,rows,cards,{c.name for c in cards},counts="counts UNKNOWN")
    assert actionable and "2 P0 active" in text
    assert "deferred-p0 P0 (not READY)" in text
    assert "1 P0, 33 P1" in text
    assert "counts UNKNOWN" in text
    assert text.count("unowned-00") == 1


def test_future_or_malformed_log_ledger_cannot_hide_a_digest(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(time,"time",lambda:1000)
    path=tmp_path/"notify/role_ranking_log.json"
    path.parent.mkdir()
    for value in ([],dict(key="same",at=999999),dict(key="same",at=True)):
        path.write_text(json.dumps(value))
        logs=[]
        ranking._log_digest(tmp_path,"digest","same",logs.append)
        assert logs==["digest"]


def test_routine_advisory_does_not_print_a_second_list(tmp_path, capsys):
    cards,ready,rows=scenario()
    reg=SimpleNamespace(all=lambda:Answer.complete_read(cards,how="fixture"))
    ranking.sweep(tmp_path,reg,SimpleNamespace(exists=lambda p:True),
        snapshot=lambda:(ready,rows),counts_reader=lambda root:"counts")
    output=capsys.readouterr().out
    assert output.count("unowned-33")==1
    assert output.count("worker0:")==1
