from types import SimpleNamespace
from shantytown import cli, session_budget as sb, tend
from shantytown.protocols import Agent, WorkItem
import pytest

@pytest.mark.parametrize("lost", [False, True])
def test_measured_budget_positive_and_unknown_refusal(tmp_path, monkeypatch, lost):
    limits=sb.Limits(max_items=4)
    source=sb.Spend(session="source", items=4)
    hit=sb.Ceiling("items",4,4,source)
    def gate(root, name, now=None):
        if name=="source": return limits, source, hit
        return limits, sb.Spend(session="" if lost else "target",items=0,signal_lost=lost), None
    monkeypatch.setattr(sb,"gate",gate)
    import shantytown.work_item as wi
    comments={}
    def rows(tracker, item, body=None):
        if body is not None:comments.setdefault(item,[]).append({"body":body})
        return comments.get(item,[])
    monkeypatch.setattr(wi,"_comments",rows)
    sent=[]
    class Dispatcher:
        tracker=object()
        def go(self,item,target,**kwargs):sent.append((item,target))
    cli._ceiling_transfer_sweep(
        SimpleNamespace(root=tmp_path,dry_run=False),
        [Agent(name="source",harness="codex"),Agent(name="target",harness="claude")],
        SimpleNamespace(findings=[tend.Finding("source","up","ok"),tend.Finding("target","up","ok")]),
        dispatcher=Dispatcher(),plate=lambda n:WorkItem(id="held",assignee=n,status="open"),
        owner_count=lambda n:0,gaming=SimpleNamespace(held=False),log=lambda msg:None)
    assert sent==([] if lost else [("held","target")])
