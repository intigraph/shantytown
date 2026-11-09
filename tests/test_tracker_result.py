"""The real item dispatcher must retain outcome, not parse failures as empty."""
from argparse import Namespace
import json
import subprocess
from urllib.error import HTTPError

import pytest
from shantytown import cli
from shantytown.protocols import WorkItem
from shantytown.tracker_result import observe


def invoke(monkeypatch, capsys, tracker, action="show", **extra):
    monkeypatch.setattr(cli, "_tracker", lambda a: tracker)
    a = Namespace(cmd="item", item_action=action, item="exact-1",
        dry_run=False, result_json=True, **extra)
    code = cli._run_command(a)
    text = capsys.readouterr()
    assert "Traceback" not in text.err
    return code, json.loads(text.out)


@pytest.mark.parametrize("status,category", [(401,"AUTH"),(403,"POLICY"),(408,"TIMEOUT")])
def test_http_failure_is_structured_private_and_not_empty(monkeypatch,capsys,status,category):
    class Tracker:
        def get(self, item):
            raise HTTPError("https://private.invalid/Bearer-secret",status,"private body",None,None)
    code, v = invoke(monkeypatch,capsys,Tracker())
    assert code != 0 and v["ok"] is False and v["data"] is None
    assert v["error"]["category"] == category
    assert v["mutation_outcome"] == "NOT_APPLICABLE"
    assert "secret" not in json.dumps(v) and "private body" not in json.dumps(v)


def test_missing_input_is_proven_not_submitted(monkeypatch,capsys,tmp_path):
    class Tracker:
        def get(self,item): return WorkItem(item)
        def update(self,*a,**kw): pytest.fail("must never submit")
    code, v = invoke(monkeypatch,capsys,Tracker(),"comment",file=tmp_path/"absent")
    assert code and v["error"]["category"] == "MISSING_INPUT"
    assert v["phase"] == "INPUT" and v["mutation_outcome"] == "NOT_WRITTEN"


@pytest.mark.parametrize("committed", [False, True])
def test_timeout_cannot_justify_retry_even_if_commit_landed(monkeypatch,capsys,committed):
    class Tracker:
        calls = 0
        status = "open"
        def get(self,item): return WorkItem(item,status=self.status)
        def update(self,*a,**kw):
            self.calls += 1
            if committed: self.status = "in_progress"
            raise subprocess.TimeoutExpired("private arguments",30)
    t = Tracker()
    code, v = invoke(monkeypatch,capsys,t,"update",status="in_progress")
    assert code and v["mutation_outcome"] == "UNKNOWN"
    assert v["phase"] == "SUBMIT" and v["error"]["category"] == "TIMEOUT"
    assert t.calls == 1
    assert t.get("exact-1").status == ("in_progress" if committed else "open")
    assert "private arguments" not in json.dumps(v)


def test_sdk_conflict_code_survives_wrapper(monkeypatch,capsys):
    class Tracker:
        def get(self,item): return WorkItem(item)
        def update(self,*a,**kw):
            observe(subprocess.CompletedProcess([],4,'{"error":{"code":"CONFLICT","message":"private"}}','private'))
            raise RuntimeError("secondary diagnostic")
    code,v = invoke(monkeypatch,capsys,Tracker(),"update",status="open")
    assert code == 4 and v["error"]["code"] == "CONFLICT"
    assert v["error"]["category"] == "CONFLICT"


def test_positive_populated_read_and_malformed_negative(monkeypatch,capsys):
    class Good:
        def get(self,item): return WorkItem(item,title="populated")
    code,v = invoke(monkeypatch,capsys,Good())
    assert code == 0 and v["data"]["title"] == "populated"
    class Broken:
        def get(self,item): return json.loads("not json")
    code,v = invoke(monkeypatch,capsys,Broken())
    assert code and v["error"]["category"] == "MALFORMED_RESPONSE"


def test_timeout_before_submit_has_no_write(monkeypatch,capsys):
    class Tracker:
        def get(self,item): raise TimeoutError("before submit")
        def update(self,*a,**kw): pytest.fail("never submit")
    code,v = invoke(monkeypatch,capsys,Tracker(),"update",status="open")
    assert code and v["phase"] == "READ"
    assert v["mutation_outcome"] == "NOT_WRITTEN"


def test_failed_readback_is_unknown_not_replayed(monkeypatch,capsys):
    class Tracker:
        writes = 0
        def get(self,item):
            if self.writes: raise TimeoutError("readback unavailable")
            return WorkItem(item)
        def update(self,*a,**kw): self.writes += 1
    t = Tracker()
    code,v = invoke(monkeypatch,capsys,t,"update",status="open")
    assert code and t.writes == 1
    assert v["phase"] == "READBACK" and v["mutation_outcome"] == "UNKNOWN"


def test_untrusted_error_fields_cannot_break_envelope(monkeypatch,capsys):
    class Tracker:
        def get(self,item):
            observe(subprocess.CompletedProcess([],7,'{"error":{"code":{},"details":{"http_status":[]}}}',''))
            raise RuntimeError("private upstream")
    code,v = invoke(monkeypatch,capsys,Tracker())
    assert code == 7 and v["error"]["code"] == "UNKNOWN"
    assert v["error"]["http_status"] is None


def test_exact_absence_and_unsupported_identity_are_distinct(monkeypatch,capsys):
    from shantytown.tracker_result import ItemNotFound
    class Missing:
        def get(self,item): raise ItemNotFound(item)
    code,v = invoke(monkeypatch,capsys,Missing())
    assert code == 3 and v["error"]["category"] == "NOT_FOUND"
    class Unsupported:
        def get(self,item): raise LookupError("unsupported identity")
    code,v = invoke(monkeypatch,capsys,Unsupported())
    assert code and v["error"]["category"] == "UNKNOWN"


@pytest.mark.parametrize("landed", [False,True])
def test_comment_timeout_reconciles_without_a_second_submission(monkeypatch,capsys,tmp_path,landed):
    from datetime import datetime,timezone
    from shantytown.sd import SdTracker
    class Tracker(SdTracker):
        def __init__(self): self.writes = 0; self.rows = []
        def get(self,item): return WorkItem(item)
        def _bd_for(self,item,*command):
            if command[:2] == ("comments","add"):
                self.writes += 1
                if landed:
                    self.rows.append({"text":"private exact body","created_at":datetime.now(timezone.utc).isoformat()})
                raise subprocess.TimeoutExpired("private command",30)
            assert command[:2] == ("comments",item)
            return subprocess.CompletedProcess([],0,json.dumps(self.rows),"")
    body=tmp_path/"body.txt"; body.write_text("private exact body")
    t=Tracker()
    code,v=invoke(monkeypatch,capsys,t,"comment",file=body)
    assert t.writes == 1 and len(t.rows) == int(landed)
    if landed:
        assert code == 0 and v["mutation_outcome"] == "COMMITTED"
    else:
        assert code and v["mutation_outcome"] == "UNKNOWN"
        assert v["error"]["category"] == "TIMEOUT"
    assert "private exact body" not in json.dumps(v)
