import json
from types import SimpleNamespace

import pytest

from shantytown import cli, crew_rules, session_anchor
from shantytown.answer import Answer
from shantytown.protocols import Agent

NS = "https://crew.example/roles/"


def row(role, **extra):
    return {"rule": NS+role+"-duty", "scope": NS+role, "topic": "responsibilities",
            "summary": role+" governed duty", "text": "full governed text", **extra}


def configure(root):
    (root/"shantytown.toml").write_text('[env]\nSHANTY_RULES_QUERY="crew_rules"\nSHANTY_ONTO_NS="'+NS+'"\nQUIPU_SERVER="https://graph.example"\n')


def test_role_projection_selects_only_its_scope_and_carries_canonical_iri(tmp_path):
    configure(tmp_path)
    calls = []
    def reader(root, name, params):
        calls.append((name,params))
        return [{"topic":"global"}, row(params['role'].removeprefix(NS))]
    actual = crew_rules.load(tmp_path,["worker","administrator"],reader=reader)
    assert [r.summaries for r in actual]==[("administrator governed duty",),("worker governed duty",)]
    assert calls==[("crew_rules",{"role":NS+"administrator"}),("crew_rules",{"role":NS+"worker"})]
    assert "administrator governed duty" not in crew_rules.render(actual[1:])


@pytest.mark.parametrize("rows",[[],[{"topic":"global"}],[row("administrator")],
                                  [row("worker",summary="")],[row("worker"),row("worker")]])
def test_empty_malformed_and_foreign_scope_are_unknown(tmp_path, rows):
    configure(tmp_path)
    report=crew_rules.load(tmp_path,["worker"],reader=lambda *a:rows)
    assert report[0].unknown
    assert "UNKNOWN" in crew_rules.render(report)


def test_missing_namespace_or_failed_transport_has_no_local_rulebook(tmp_path):
    assert crew_rules.load(tmp_path,["worker"])[0].unknown
    configure(tmp_path)
    def fail(*args):raise OSError("unreadable")
    assert crew_rules.load(tmp_path,["worker"],reader=fail)[0].unknown


@pytest.mark.parametrize("body",[{"error":"refused"},{"count":0,"rows":[],"truncated":True},
                                 {"count":2,"rows":[{}],"truncated":False},
                                 {"count":200,"rows":[{}]*200,"truncated":False}])
def test_query_refusal_or_unproven_completeness_never_becomes_empty(tmp_path,body,monkeypatch):
    configure(tmp_path)
    monkeypatch.setattr(crew_rules,"post",lambda *a,**k:json.dumps(body).encode())
    with pytest.raises(ValueError):
        crew_rules.ask(tmp_path,"crew_rules",{})


def test_catalogue_reads_once_includes_reviewer_and_separates_roles(tmp_path,monkeypatch):
    configure(tmp_path);calls=[]
    def ask(root,query,params):
        calls.append(params)
        return [row("administrator"),row("lead"),row("keeper"),row("worker"),row("reviewer")]
    monkeypatch.setattr(crew_rules,"ask",ask)
    actual=crew_rules.load_all(tmp_path,["worker"])
    assert calls==[{"role":"*"}]
    assert {r.role for r in actual}=={"administrator","lead","keeper","worker","reviewer"}
    assert all(not r.unknown for r in actual)


def test_actual_anchor_and_session_start_use_graph_responsibilities(tmp_path,monkeypatch,capsys):
    configure(tmp_path)
    cards=[Agent(name="chief",role="administrator",pane="p"),
           Agent(name="team",role="lead",reports_to="chief",pane="p"),
           Agent(name="member",role="worker",reports_to="team",pane="p")]
    reg=SimpleNamespace(all=lambda:Answer.complete_read(cards,how="fixture"),
                        get=lambda n:next(c for c in cards if c.name==n))
    monkeypatch.setattr(cli,"_registry",lambda a:reg)
    monkeypatch.setattr(cli,"_panes",lambda a:SimpleNamespace(exists=lambda *a:True,cmdline=lambda *a:None))
    monkeypatch.setattr(cli,"_plate",lambda *a,**k:lambda n:None)
    monkeypatch.setattr(cli,"_lead_status",lambda *a:lambda n:True)
    monkeypatch.setattr(crew_rules,"ask",lambda root,name,params:[row(params['role'].removeprefix(NS))])
    for name,role in [("chief","administrator"),("team","lead"),("member","worker")]:
        assert cli.main(["--root",str(tmp_path),"--backend","files","anchor",name])==0
        text=capsys.readouterr().out
        assert role+" governed duty" in text
        assert "ROLE RESPONSIBILITIES" in text
    monkeypatch.setattr(session_anchor,"_run_anchor",lambda *a:(0,text))
    assert "worker governed duty" in session_anchor.render(str(tmp_path),"member")
    monkeypatch.setattr(crew_rules,"ask",lambda *a:[])
    assert cli.main(["--root",str(tmp_path),"--backend","files","anchor","member"])==0
    assert "worker: UNKNOWN" in capsys.readouterr().out


def test_roles_show_projects_all_five_governed_responsibilities(tmp_path,monkeypatch,capsys):
    configure(tmp_path)
    cards=[Agent(name='chief',role='administrator')]
    monkeypatch.setattr(cli,'_registry',lambda a:SimpleNamespace(all=lambda:Answer.complete_read(cards,how='fixture')))
    monkeypatch.setattr(crew_rules,'ask',lambda *a:[row(role) for role in ['administrator','lead','keeper','worker','reviewer']])
    assert cli.main(['--root',str(tmp_path),'fleet','roles','show'])==0
    text=capsys.readouterr().out
    for role in ['administrator','lead','keeper','worker','reviewer']:
        assert role+' governed duty' in text
