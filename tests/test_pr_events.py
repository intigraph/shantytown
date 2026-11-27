"""`st agent spawn --drain-events` (aegis-za4f.21): chaski's pr-lifecycle
events recruit ephemeral jobs with no crew in the loop. Each check here is
also shown saying no: a bad line, a stale head, a refusal, a missing item."""
from __future__ import annotations

import json
import re

import pytest

from shantytown import cli
from shantytown import ephemeral as eph
from shantytown import pr_events as pe

from test_ephemeral import _st, store  # noqa: F401

HEAD = "a" * 40
NEWER = "b" * 40
REASON = {"review": "new-head-unreviewed", "task": "changes-requested",
          "merge": "green-and-approved"}


def _ev(job="task", item="it-1", head=HEAD, pr=7, repo="o/n", reason=None, **over):
    ev = {"event_id": pe.event_id(repo, pr, head, job), "repo": repo, "pr": pr,
          "head": head, "job": job, "item": item, "reason": reason or REASON.get(job, "ci-red"),
          "observed_at": "2026-11-27T08:00:00Z"}
    ev.update(over)
    return ev


def _write(path, *events):
    path.write_text("".join((e if isinstance(e, str) else json.dumps(e)) + "\n"
                            for e in events))
    return path


# --- the contract -----------------------------------------------------------

def test_event_id_is_the_contract_sha256():
    import hashlib
    want = hashlib.sha256(b"intigraph/quipu|1354|" + HEAD.encode() + b"|review").hexdigest()
    assert pe.event_id("intigraph/quipu", 1354, HEAD, "review") == want


@pytest.mark.parametrize("bad,why", [
    ({"head": "abc"}, "40-hex"),
    ({"pr": 0}, "positive"),
    ({"pr": True}, "positive"),
    ({"repo": "no-slash"}, "OWNER/NAME"),
    ({"job": "deploy"}, "job"),
    ({"reason": "vibes"}, "reason"),
    ({"item": "--root=/etc"}, "work item"),
    ({"event_id": "0" * 64}, "sha256(repo|pr|head|job)"),
])
def test_parse_says_no_to_each_bad_field(bad, why):
    with pytest.raises(ValueError, match=re.escape(why)):
        pe.parse(json.dumps(_ev(**bad)))


def test_a_merge_never_comes_from_a_red_head():
    # The merge job re-verifies, but an emitter pairing merge with ci-red is a
    # bug, and this consumer refuses to be the one that acts on it.
    with pytest.raises(ValueError, match="never recruits a merge"):
        pe.parse(json.dumps(_ev(job="merge", reason="ci-red")))
    assert pe.parse(json.dumps(_ev(job="task", reason="ci-red")))["job"] == "task"


def test_parse_accepts_a_null_item():
    assert pe.parse(json.dumps(_ev(item=None)))["item"] is None


# --- the drain --------------------------------------------------------------

def test_an_event_spawns_once_and_never_again(store, tmp_path, capsys):
    root, _panes, launched = store
    events = _write(tmp_path / "ev.jsonl", _ev())
    assert _st(root, "--drain-events", str(events)) == cli.OK
    (rec,) = eph.records(root)
    assert (rec["job"], rec["item"], rec["repo"], rec["pr"]) == ("task", "it-1", "o/n", 7)
    assert rec["track"] == "roadmap" and len(launched) == 1
    assert "admitted 1" in capsys.readouterr().out
    # The same line read again (chaski appends; the file is re-read whole).
    assert _st(root, "--drain-events", str(events)) == cli.OK
    assert len(launched) == 1 and len(eph.records(root)) == 1
    assert "already settled 1" in capsys.readouterr().out


def test_over_cap_the_event_queues_a_ticket_and_is_settled(store, tmp_path, monkeypatch, capsys):
    root, _panes, launched = store                       # max_agents = 1
    monkeypatch.setattr(eph, "kick_drain", lambda r: None)
    events = _write(tmp_path / "ev.jsonl", _ev(item="it-1", pr=7), _ev(item="it-2", pr=8))
    assert _st(root, "--drain-events", str(events)) == cli.OK
    assert len(launched) == 1
    (ticket,) = eph.tickets(root)
    assert ticket["item"] == "it-2" and ticket["pr"] == 8
    assert "QUEUED" in capsys.readouterr().out
    # Queued is the cap doing its job: the ticket carries it, not the events.
    assert _st(root, "--drain-events", str(events)) == cli.OK
    assert len(eph.tickets(root)) == 1


def test_a_refused_spawn_stays_pending_and_runs_when_the_refusal_clears(store, tmp_path, monkeypatch, capsys):
    root, _panes, launched = store
    events = _write(tmp_path / "ev.jsonl", _ev())
    monkeypatch.setattr(cli, "_spawn_governor_refusal", lambda a, card: "governor: held")
    assert _st(root, "--drain-events", str(events)) == cli.CANNOT_TELL
    err = capsys.readouterr().err
    assert "governor: held" in err and "offered again" in err
    assert launched == [] and pe.settled(root) == {}
    monkeypatch.setattr(cli, "_spawn_governor_refusal", lambda a, card: None)
    assert _st(root, "--drain-events", str(events)) == cli.OK
    assert len(launched) == 1


def test_a_stale_head_is_superseded_not_spawned(store, tmp_path, capsys):
    # quipu#1354: an approval and a merge for a head the PR had moved past.
    root, _panes, launched = store
    events = _write(tmp_path / "ev.jsonl",
                    _ev(job="review", head=HEAD), _ev(job="task", head=NEWER, item="it-1"))
    assert _st(root, "--drain-events", str(events)) == cli.OK
    out = capsys.readouterr().out
    assert "superseded review o/n#7" in out
    assert [r["job"] for r in eph.records(root)] == ["task"]
    outcomes = {r["head"]: r["outcome"] for r in pe.settled(root).values()}
    assert outcomes == {HEAD: "superseded", NEWER: "admitted"}


def test_a_new_head_re_arms_the_same_job(store, tmp_path, monkeypatch):
    root, _panes, launched = store
    monkeypatch.setattr(eph, "kick_drain", lambda r: None)
    path = tmp_path / "ev.jsonl"
    _write(path, _ev(head=HEAD))
    assert _st(root, "--drain-events", str(path)) == cli.OK
    _write(path, _ev(head=HEAD), _ev(head=NEWER))
    assert _st(root, "--drain-events", str(path)) == cli.OK
    # The second head's event is admitted (queued: the first job holds the slot).
    assert len(launched) + len(eph.tickets(root)) == 2


def test_no_item_stays_pending_and_says_why(store, tmp_path, capsys):
    root, _panes, launched = store
    events = _write(tmp_path / "ev.jsonl", _ev(item=None))
    assert _st(root, "--drain-events", str(events)) == cli.CANNOT_TELL
    assert "no work item" in capsys.readouterr().err
    assert launched == [] and pe.settled(root) == {}


def test_a_bad_line_is_reported_and_the_good_one_still_spawns(store, tmp_path, capsys):
    root, _panes, launched = store
    events = _write(tmp_path / "ev.jsonl", "{not json", _ev(event_id="f" * 64), _ev())
    assert _st(root, "--drain-events", str(events)) == cli.CANNOT_TELL
    err = capsys.readouterr().err
    assert "line 1: not JSON" in err and "line 2: event_id" in err
    assert len(launched) == 1


def test_dry_run_spawns_and_settles_nothing(store, tmp_path, capsys):
    root, _panes, launched = store
    events = _write(tmp_path / "ev.jsonl", _ev())
    assert _st(root, "--drain-events", str(events), "--dry-run") == cli.OK
    out = capsys.readouterr().out
    assert "would spawn --ephemeral --job task --item it-1 --repo o/n --pr 7" in out
    assert launched == [] and pe.settled(root) == {}


def test_an_ephemeral_agent_cannot_drain_events(store, tmp_path, monkeypatch, capsys):
    root, panes, launched = store
    panes.verified_actor = "eph-task-abcdef"
    monkeypatch.setenv("SHANTY_AGENT", "eph-task-abcdef")
    events = _write(tmp_path / "ev.jsonl", _ev())
    assert _st(root, "--drain-events", str(events)) == cli.REFUSED
    assert "cannot drain PR events" in capsys.readouterr().err
    assert launched == []


def test_a_missing_file_is_refused(store, tmp_path, capsys):
    root, _panes, _launched = store
    assert _st(root, "--drain-events", str(tmp_path / "absent.jsonl")) == cli.REFUSED
    assert "cannot read" in capsys.readouterr().err


def _age_first_refusal(root, seconds):
    p = pe.ledger_path(root)
    lines = [json.loads(line) for line in p.read_text().splitlines()]
    for rec in lines:
        if rec["outcome"] == "refused":
            rec["at"] -= seconds
    p.write_text("".join(json.dumps(r) + "\n" for r in lines))


def test_a_permanent_refusal_expires_so_the_drain_can_go_clean(store, tmp_path, monkeypatch, capsys):
    # Review of #776: a merge pin mismatch or closed PR re-spawned on every
    # drain and held exit 2 forever.
    root, _panes, launched = store
    events = _write(tmp_path / "ev.jsonl", _ev())
    monkeypatch.setattr(cli, "_spawn_governor_refusal", lambda a, card: "governor: held")
    assert _st(root, "--drain-events", str(events)) == cli.CANNOT_TELL
    assert _st(root, "--drain-events", str(events)) == cli.CANNOT_TELL   # inside the TTL: still pending
    assert pe.settled(root) == {}
    assert len(pe.first_refused(root)) == 1        # dated once, not once per drain
    capsys.readouterr()
    _age_first_refusal(root, pe.PENDING_TTL_S + 1)
    assert _st(root, "--drain-events", str(events)) == cli.CANNOT_TELL   # the expiry itself is loud
    assert "expired task o/n#7" in capsys.readouterr().err
    assert [r["outcome"] for r in pe.settled(root).values()] == ["expired"]
    assert _st(root, "--drain-events", str(events)) == cli.OK            # and then clean
    assert launched == []


def test_an_event_already_in_flight_is_not_launched_twice(store, tmp_path, capsys):
    # A drain that crashed after the spawn but before settle() offers the event
    # again; the spawn path would happily launch a second job for it.
    root, _panes, launched = store
    events = _write(tmp_path / "ev.jsonl", _ev())
    assert _st(root, "--drain-events", str(events)) == cli.OK
    p = pe.ledger_path(root)                       # the lost settle: keep only the intent
    p.write_text("".join(line + "\n" for line in p.read_text().splitlines()
                         if json.loads(line)["outcome"] == "spawning"))
    capsys.readouterr()
    assert _st(root, "--drain-events", str(events)) == cli.OK
    assert len(launched) == 1 and len(eph.records(root)) == 1
    assert "already in flight as eph-task-" in capsys.readouterr().out
    (rec,) = pe.settled(root).values()
    assert rec["outcome"] == "admitted"


def test_a_new_head_task_is_not_mistaken_for_the_running_one(store, tmp_path, monkeypatch):
    # Task records keep no head, so a head-less in_flight match must only be
    # asked about an event that was actually spawned, or the new head's fix
    # would settle against the old head's job and never run.
    root, _panes, launched = store
    monkeypatch.setattr(eph, "kick_drain", lambda r: None)
    path = tmp_path / "ev.jsonl"
    _write(path, _ev(head=HEAD))
    assert _st(root, "--drain-events", str(path)) == cli.OK
    _write(path, _ev(head=HEAD), _ev(head=NEWER))
    assert _st(root, "--drain-events", str(path)) == cli.OK
    assert len(eph.tickets(root)) == 1
    (new,) = [r for r in pe.settled(root).values() if r["head"] == NEWER]
    assert "in flight" not in new.get("detail", "")


def test_a_malformed_line_holds_exit_2_once_not_forever(store, tmp_path, capsys):
    # The file is append-only, so a bad line never leaves it. Before this it
    # held exit 2 on every later drain (review of #776).
    root, _panes, launched = store
    path = _write(tmp_path / "ev.jsonl", "{not json", _ev())
    assert _st(root, "--drain-events", str(path)) == cli.CANNOT_TELL
    assert "skipped line 1" in capsys.readouterr().err
    assert len(launched) == 1                      # the good line still drained
    assert _st(root, "--drain-events", str(path)) == cli.OK
    assert "reported before" in capsys.readouterr().err
    # A different bad line is new, so it is loud again.
    _write(path, "{not json", _ev(), "[]")
    assert _st(root, "--drain-events", str(path)) == cli.CANNOT_TELL


def test_a_dry_run_records_no_malformed_line(store, tmp_path):
    root, _panes, _launched = store
    path = _write(tmp_path / "ev.jsonl", "{not json")
    assert _st(root, "--drain-events", str(path), "--dry-run") == cli.CANNOT_TELL
    assert pe.malformed_seen(root) == set()
    assert _st(root, "--drain-events", str(path)) == cli.CANNOT_TELL


def test_a_head_less_hand_spawned_job_does_not_settle_a_new_head():
    # Event B was attempted at t=100 and refused; a hand-spawned task on an
    # older head of the same PR (no head on its record, spawned at t=50) must
    # not count as B's launch, or B would be settled and never run.
    ev = pe.parse(json.dumps(_ev(head=NEWER)))
    hand = {"name": "eph-task-hand", "job": "task", "repo": "o/n", "pr": 7,
            "head": None, "spawned_at": 50.0}
    old_merge = {**hand, "name": "eph-task-old", "head": HEAD, "spawned_at": 200.0}
    assert pe.in_flight(ev, [hand, old_merge], [], since=100.0) is None
    # The drain's own launch: head-less but born after the intent line.
    mine = {**hand, "name": "eph-task-mine", "spawned_at": 101.0}
    assert pe.in_flight(ev, [hand, mine], [], since=100.0) == "eph-task-mine"
    ticket = {"id": "q-1", "job": "task", "repo": "o/n", "pr": 7, "head": None,
              "enqueued_at": 100.0}
    assert pe.in_flight(ev, [], [ticket], since=100.0) == "q-1"
    exact = {**hand, "name": "eph-merge-x", "head": NEWER, "spawned_at": 1.0}
    assert pe.in_flight(ev, [exact], [], since=100.0) == "eph-merge-x"
