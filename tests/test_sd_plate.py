"""Remote plates never need other owners' bodies or readiness rows."""
import json
import subprocess

import pytest

from shantytown import br
from shantytown.sd import SdTracker, StoreProof


@pytest.fixture(autouse=True)
def legacy_cli_transport(monkeypatch):
    # These controls exercise the retained local/older-SDK CLI adapter.
    monkeypatch.setattr(SdTracker, "prove_store", lambda self: StoreProof(
        "--quipu", None, "https://example.test", "test"))



def tracker(monkeypatch, *, fail_owner=None, fail_ready=False):
    t = SdTracker(quipu="https://example.test", prefix="test")
    calls = []
    rows = [dict(id="a", title="blocked", assignee="worker", status="open", priority=2),
            dict(id="z", title="ready", assignee="rig/worker", status="open", priority=2),
            dict(id="h", title="held", assignee="other", status="in_progress", priority=1)]

    def run(*args):
        assert args[0] in ("list", "ready")
        assert "--assignee" in args, "an unfiltered board read escaped"
        owner = args[args.index("--assignee") + 1]
        status = args[args.index("--status") + 1] if "--status" in args else None
        calls.append((args[0], owner, status))
        if owner == fail_owner or (fail_ready and args[0] == "ready"):
            return subprocess.CompletedProcess(args, 2, "", "unreadable")
        selected = [r for r in rows if r["assignee"] == owner]
        if status is not None:
            selected = [r for r in selected if r["status"] == status]
        if args[0] == "ready":
            selected = [r for r in selected if r["id"] == "z"]
        return subprocess.CompletedProcess(args, 0, json.dumps({"issues": selected, "total": len(selected), "has_more": False}), "")

    monkeypatch.setattr(t, "_bd", run)
    return t, calls


def test_both_owner_spellings_preserve_readiness_rank_and_cache_per_agent(monkeypatch):
    t, calls = tracker(monkeypatch)
    monkeypatch.setattr(br, "name_the_blocker", lambda _, item: item)
    reader = br.plate_reader(t)
    assert reader("rig/worker").id == "z"
    assert reader("rig/worker").id == "z"
    assert calls == [("list", owner, status) for status in ("hooked", "in_progress", None)
                     for owner in ("rig/worker", "worker")] + [
                         ("ready", "rig/worker", None), ("ready", "worker", None)]
    assert reader("other").id == "h"
    assert calls[-2:] == [("list", "other", "hooked"), ("list", "other", "in_progress")]
    assert len(calls) == 10
    assert br.plate(t, "rig/worker").id == "z"


def test_owner_read_failure_remains_loud_and_strict_reader_refuses(monkeypatch, capsys):
    t, _ = tracker(monkeypatch, fail_owner="worker")
    assert br.plate(t, "rig/worker").id == "z"
    assert "PLATE INCOMPLETE" in capsys.readouterr().err
    with pytest.raises(RuntimeError, match="owner worker"):
        br.plate_reader(t, require_complete=True)("rig/worker")


def test_failed_readiness_is_unknown_and_does_not_claim_no_ready_work(monkeypatch):
    t, _ = tracker(monkeypatch, fail_ready=True)
    assert not t.plate_ready_ids("rig/worker").complete
    from shantytown.answer import PartialAnswer
    with pytest.raises(PartialAnswer):
        t.plate_ready_ids("rig/worker").exact()
    assert br.plate(t, "rig/worker").id == "a"


def test_inbox_scopes_recipient_and_closed_receipts_and_refuses_partial(monkeypatch):
    from shantytown.inbox import TrackerInbox
    from shantytown.answer import PartialAnswer
    t = SdTracker(quipu="https://example.test", prefix="test")
    monkeypatch.setattr(t, "_use_remote_projection", lambda: False)
    calls = []

    def run(*args):
        assert "--assignee" in args and "--title-contains" in args
        owner = args[args.index("--assignee") + 1]
        closed = "--all" in args
        calls.append((owner, closed))
        rows = [dict(id="receipt", title="inbox: marker payload", assignee=owner,
                     status="closed" if closed else "open", priority=2)]
        return subprocess.CompletedProcess(args, 0,
            json.dumps({"issues": rows, "total": 1, "has_more": False}), "")

    monkeypatch.setattr(t, "_bd", run)
    inbox = TrackerInbox(t, lambda: (_ for _ in ()).throw(AssertionError("whole board read")),
                         items_for=t.inbox_items)
    assert len(inbox.unread("worker")) == 1
    assert inbox.find_delivery("worker", "marker").read
    assert calls == [("worker", False), ("worker", False), ("worker", True), ("worker", True)]
    monkeypatch.setattr(t, "_bd", lambda *args: subprocess.CompletedProcess(args, 0,
        '{"issues":[],"total":10,"has_more":true}', ""))
    with pytest.raises(PartialAnswer):
        inbox.unread("worker")
    with pytest.raises(PartialAnswer):
        inbox.find_delivery("worker", "marker")

@pytest.mark.parametrize("stamp", ["2000-01-01", "2099-01-01", "malformed", ""])
def test_deferral_candidates_keep_both_representations_without_whole_open_read(monkeypatch, stamp):
    t = SdTracker(quipu="https://example.test", prefix="test")
    calls = []
    def run(*args):
        status = args[args.index("--status") + 1]
        calls.append(args)
        assert ("--defer-until-present" in args) == (status == "open")
        rows = [dict(id=status, status=status, defer_until=stamp if status == "open" else None)]
        return subprocess.CompletedProcess(args, 0, json.dumps(
            dict(issues=rows, total=1, has_more=False)), "")
    monkeypatch.setattr(t, "_bd", run)
    assert {r["id"] for r in t.deferred_rows().exact()} == {"deferred", "open"}
    assert len(calls) == 2

@pytest.mark.parametrize("payload", [
    dict(issues=[], total=2, has_more=True),
    dict(issues=[dict(id="open", status="open")], total=1, has_more=False),
])
def test_deferral_candidates_refuse_partial_or_unscoped_open_rows(monkeypatch, payload):
    from shantytown.answer import PartialAnswer
    t = SdTracker(quipu="https://example.test", prefix="test")
    monkeypatch.setattr(t, "_bd", lambda *args: subprocess.CompletedProcess(
        args, 0, json.dumps(payload), ""))
    with pytest.raises(PartialAnswer):
        t.deferred_rows().exact()


@pytest.mark.parametrize("payload", [
    {"issues": [{"id": "z"}], "total": 2, "has_more": True},
    {"issues": [{"id": "z"}], "total": 2, "has_more": False},
    {"issues": [{"id": "z"}, {}], "total": 2, "has_more": False},
    [{"id": "z"}, {}], [{"id": "z"}, {"id": 7}],
    [{"id": "z"}, {"id": " "}], [{"id": "z"}, None],
])
def test_invalid_readiness_is_unknown_and_preserves_plate_ranking(monkeypatch, payload):
    from shantytown.answer import PartialAnswer
    t, _ = tracker(monkeypatch)
    original = t._bd
    def read(*args):
        if args[0] == "ready":
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        return original(*args)
    monkeypatch.setattr(t, "_bd", read)
    answer = t.plate_ready_ids("rig/worker")
    assert not answer.complete
    with pytest.raises(PartialAnswer):
        answer.exact()
    assert br.plate(t, "rig/worker").id == "a", "unknown readiness changed the fallback rank"


@pytest.mark.parametrize("payload", [
    [{"id": "z"}],
    {"issues": [{"id": "z"}], "total": 1, "has_more": False},
    [], {"issues": [], "total": 0, "has_more": False},
])
def test_ready_bare_array_and_complete_envelope_controls(monkeypatch, payload):
    t = SdTracker(quipu="https://example.test", prefix="test")
    monkeypatch.setattr(t, "_bd", lambda *args: subprocess.CompletedProcess(
        args, 0, json.dumps(payload), ""))
    expected = {"z"} if payload else set()
    if isinstance(payload, dict) and not payload["issues"]:
        expected = set()
    assert t.plate_ready_ids("worker").exact() == expected


@pytest.mark.parametrize("modern_priority,legacy_priority,modern_date,legacy_date,expected", [
    (2, 2, "2020-01-01T00:00:00Z", "2019-01-01T00:00:00Z", ["legacy", "modern"]),
    (1, 2, "2020-01-01T00:00:00Z", "2019-01-01T00:00:00Z", ["modern", "legacy"]),
    (2, 2, "2020-01-01T00:00:00Z", "2020-01-01T00:00:00Z", ["legacy", "modern"]),
])
def test_scoped_inbox_keeps_legacy_mail_and_rejects_partial_prefix_reads(
        monkeypatch, modern_priority, legacy_priority, modern_date, legacy_date, expected):
    from shantytown.inbox import TrackerInbox
    from shantytown.answer import PartialAnswer
    t = SdTracker(quipu="https://example.test", prefix="test")
    monkeypatch.setattr(t, "_use_remote_projection", lambda: False)
    rows = [dict(id="modern", title="inbox: modern", assignee="worker", status="open",
                 priority=modern_priority, created_at=modern_date),
            dict(id="legacy", title="  mail: legacy", assignee="worker", status="open",
                 priority=legacy_priority, created_at=legacy_date),
            dict(id="work", title="work mentions mail: in text", assignee="worker", status="open")]
    calls = []
    def run(*args):
        assert args[args.index("--assignee") + 1] == "worker"
        prefix = args[args.index("--title-contains") + 1]
        calls.append(prefix)
        selected = [row for row in rows if prefix in row["title"]]
        return subprocess.CompletedProcess(args, 0,
            json.dumps({"issues": selected, "total": len(selected), "has_more": False}), "")
    monkeypatch.setattr(t, "_bd", run)
    assert {item.id for item in t.inbox_items("worker").exact()} == {"modern", "legacy"}
    assert [item.id for item in t.inbox_items("worker").exact()] == expected
    inbox = TrackerInbox(t, lambda: (_ for _ in ()).throw(AssertionError("whole board read")),
                         items_for=t.inbox_items)
    assert {message.id for message in inbox.unread("worker")} == {"modern", "legacy"}
    assert set(calls) == {"inbox:", "mail:"}
    def partial(*args):
        result = run(*args)
        if args[args.index("--title-contains") + 1] == "mail:":
            payload = json.loads(result.stdout);payload["has_more"] = True
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        return result
    monkeypatch.setattr(t, "_bd", partial)
    with pytest.raises(PartialAnswer):
        inbox.unread("worker")

@pytest.mark.parametrize('status', ['hooked', 'in_progress'])
def test_held_plate_never_reads_open_queue_or_readiness(monkeypatch, status):
    t = SdTracker(quipu='https://example.test', prefix='test')
    calls = []
    def run(*args):
        assert args[0] == 'list' and '--status' in args
        asked = args[args.index('--status') + 1]
        owner = args[args.index('--assignee') + 1]
        calls.append((asked, owner))
        rows = [dict(id='held', title='work', assignee=owner, status=status, priority=0)] if asked == status else []
        return subprocess.CompletedProcess(args, 0, json.dumps(dict(issues=rows, total=len(rows), has_more=False)), '')
    monkeypatch.setattr(t, '_bd', run)
    monkeypatch.setattr(br, 'name_the_blocker', lambda _, item: item)
    assert br.plate(t, 'rig/worker').id == 'held'
    assert calls == [(asked, owner) for asked in (['hooked'] if status == 'hooked' else ['hooked', 'in_progress']) for owner in ['rig/worker', 'worker']]

@pytest.mark.parametrize('kind', ['message', 'deferred', 'partial', 'failure'])
def test_held_probe_cannot_hide_fallback_work(monkeypatch, kind):
    t = SdTracker(quipu='https://example.test', prefix='test')
    calls = []
    def run(*args):
        calls.append(args)
        if args[0] == 'ready':
            return subprocess.CompletedProcess(args, 0, '[{"id":"open"}]', '')
        if '--status' not in args:
            rows = [dict(id='open', title='real work', assignee='worker', status='open')]
        else:
            if kind == 'failure':
                return subprocess.CompletedProcess(args, 2, '', 'unreadable')
            rows = [dict(id='held', title='inbox: message' if kind == 'message' else 'work', assignee='worker', status='in_progress')]
            if kind == 'deferred':
                rows[0]['defer_until'] = '2099-01-01T00:00:00Z'
            if kind == 'partial':
                return subprocess.CompletedProcess(args, 0, json.dumps(dict(issues=rows, total=2, has_more=True)), '')
        return subprocess.CompletedProcess(args, 0, json.dumps(dict(issues=rows, total=len(rows), has_more=False)), '')
    monkeypatch.setattr(t, '_bd', run)
    monkeypatch.setattr(br, 'name_the_blocker', lambda _, item: item)
    assert br.plate(t, 'worker').id == 'open'
    assert any(args[0] == 'list' and '--status' not in args for args in calls)
    assert any(args[0] == 'ready' for args in calls)
