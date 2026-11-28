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


def _end_all(root):
    for r in eph.live(root):
        eph.write(root, {**r, "state": eph.DONE})


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
    # The first head's task still runs on this PR, so the second is held back
    # (aegis-8et: two task jobs on one branch race their pushes). It is
    # deferred before the aegis-bmu3 one-task-per-item refusal: no exit 2, no
    # ticket, and not settled against the old head...
    assert _st(root, "--drain-events", str(path)) == cli.OK
    assert len(launched) == 1 and eph.tickets(root) == []
    assert NEWER not in {r["head"] for r in pe.settled(root).values()}
    # ...and re-armed: it launches once that job ends.
    (first,) = eph.live(root)
    assert _st(root, "--stop", first["name"]) == cli.OK
    assert _st(root, "--drain-events", str(path)) == cli.OK
    assert len(launched) == 2


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
    # A task on the old head must hold the branch without settling the new
    # head's fix against the old job.
    root, _panes, launched = store
    monkeypatch.setattr(eph, "kick_drain", lambda r: None)
    path = tmp_path / "ev.jsonl"
    _write(path, _ev(head=HEAD))
    assert _st(root, "--drain-events", str(path)) == cli.OK
    _write(path, _ev(head=HEAD), _ev(head=NEWER))
    # Held back while the old head's task runs (deferred, not refused), and
    # NOT settled against it.
    assert _st(root, "--drain-events", str(path)) == cli.OK
    assert [r for r in pe.settled(root).values() if r["head"] == NEWER] == []
    (first,) = eph.live(root)
    assert _st(root, "--stop", first["name"]) == cli.OK
    assert _st(root, "--drain-events", str(path)) == cli.OK
    (new,) = [r for r in pe.settled(root).values() if r["head"] == NEWER]
    assert new["outcome"] == "admitted" and "in flight" not in new.get("detail", "")
    assert len(launched) == 2


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


# --- aegis-qi22: a launch that always fails, and a PR that already merged ----

def test_a_launch_that_always_fails_spawns_3_times_then_is_terminal(store, tmp_path, capsys):
    # bobbin#259's merge event launched 8 jobs, each dying on the same bug.
    root, panes, launched = store
    panes.behaviour["rc"] = cli.REFUSED                  # every launch fails
    events = _write(tmp_path / "ev.jsonl", _ev())
    eid = _ev()["event_id"]
    for _ in range(pe.MAX_LAUNCH_FAILURES - 1):
        assert _st(root, "--drain-events", str(events)) == cli.CANNOT_TELL
        assert eid not in pe.settled(root)
    assert _st(root, "--drain-events", str(events)) == cli.CANNOT_TELL
    err = capsys.readouterr().err
    assert "launch-failed task o/n#7" in err
    assert pe.settled(root)[eid]["outcome"] == "launch-failed"
    for _ in range(3):                                   # terminal: never again
        assert _st(root, "--drain-events", str(events)) == cli.OK
    assert len(launched) == pe.MAX_LAUNCH_FAILURES == 3
    # Raised once to the administrator, by key, not on every drain.
    raised = [json.loads(p.read_text()) for p in (root / "events").rglob("*.json")]
    raised = [e for e in raised if e.get("reason") == "pr-event-launch-failed"]
    assert len(raised) == 1 and raised[0]["to"] == "boss" and raised[0]["item"] == "it-1"


def test_a_refusal_before_any_job_exists_is_not_a_launch_failure(store, tmp_path, monkeypatch):
    # The cap counts launches only: a governor hold makes no job, stays
    # pending and is bounded by PENDING_TTL_S, so it must not go terminal.
    root, _panes, launched = store
    monkeypatch.setattr(cli, "_spawn_governor_refusal", lambda a, card: "governor: held")
    events = _write(tmp_path / "ev.jsonl", _ev())
    for _ in range(pe.MAX_LAUNCH_FAILURES + 2):
        assert _st(root, "--drain-events", str(events)) == cli.CANNOT_TELL
    assert pe.settled(root) == {} and pe.launch_failures(root) == {}


def test_a_launch_that_fails_then_succeeds_is_admitted(store, tmp_path):
    root, panes, launched = store
    panes.behaviour["rc"] = cli.REFUSED
    events = _write(tmp_path / "ev.jsonl", _ev())
    assert _st(root, "--drain-events", str(events)) == cli.CANNOT_TELL
    panes.behaviour["rc"] = cli.OK
    assert _st(root, "--drain-events", str(events)) == cli.OK
    assert pe.settled(root)[_ev()["event_id"]]["outcome"] == "admitted"
    assert len(launched) == 2


def _forge(monkeypatch, **info):
    seen = []

    def gh(*args):
        seen.append(args[0])
        return {"state": "open", "merged": False, "head": {"sha": HEAD}, **info}
    monkeypatch.setattr(cli, "_gh_json", gh)
    return seen


@pytest.mark.parametrize("info,why", [
    ({"state": "closed", "merged": True, "merged_at": "2026-11-28T01:56:26Z"}, "pr-merged"),
    ({"state": "closed"}, "pr-closed"),
    ({"head": {"sha": NEWER}}, "head moved to bbbbbbbbbbbb"),
])
def test_a_pr_that_moved_on_spawns_nothing_and_is_settled(store, tmp_path, monkeypatch, capsys, info, why):
    root, _panes, launched = store
    seen = _forge(monkeypatch, **info)
    events = _write(tmp_path / "ev.jsonl", _ev(job="merge"))
    assert _st(root, "--drain-events", str(events)) == cli.OK
    assert launched == [] and eph.records(root) == []
    assert seen == ["repos/o/n/pulls/7"]
    rec = pe.settled(root)[_ev(job="merge")["event_id"]]
    assert rec["outcome"] == "superseded" and rec["detail"] == why
    assert why in capsys.readouterr().out
    assert _st(root, "--drain-events", str(events)) == cli.OK
    assert launched == []


def test_an_open_pr_at_the_event_head_still_spawns(store, tmp_path, monkeypatch):
    # The re-read says no only when the PR moved on.
    root, _panes, launched = store
    _forge(monkeypatch)
    events = _write(tmp_path / "ev.jsonl", _ev())
    assert _st(root, "--drain-events", str(events)) == cli.OK
    assert len(launched) == 1


# --- a job someone else launched (aegis-8et) ---------------------------------
# On 11-27 the drain launched a second job for 9 steps the administrator had
# already spawned by hand: in_flight() only knew the drain's own attempts.

def _hand_spawn(root, job="task", head=HEAD, pr=7, item="it-1"):
    assert _st(root, "--ephemeral", "--job", job, "--item", item, "--repo", "o/n",
               "--pr", str(pr), "--head", head, "--harness", "claude") == cli.OK
    (rec,) = [r for r in eph.live(root) if r["job"] == job and r["pr"] == pr]
    return rec


@pytest.mark.parametrize("job", ["review", "task", "merge"])
def test_a_hand_spawned_job_is_not_launched_twice_by_the_drain(store, tmp_path, capsys, job):
    root, _panes, launched = store
    rec = _hand_spawn(root, job=job)
    assert rec["head"] == HEAD
    if job == "review":
        assert f"This review is pinned to head {HEAD}" in eph.prompt(rec)
    assert len(launched) == 1
    capsys.readouterr()
    assert _st(root, "--drain-events", str(_write(tmp_path / "ev.jsonl", _ev(job=job)))) == cli.OK
    assert len(launched) == 1                      # no second job
    assert "already running" in capsys.readouterr().out
    assert pe.settled(root)[_ev(job=job)["event_id"]]["outcome"] == "admitted"
    eph.write(root, {**rec, "state": eph.DONE})
    assert _st(root, "--drain-events", str(tmp_path / "ev.jsonl")) == cli.OK
    assert len(launched) == 1                      # no sequential duplicate either


def test_the_deferred_event_runs_once_the_hand_spawned_job_ends(store, tmp_path):
    root, _panes, launched = store
    rec = _hand_spawn(root)
    eph.write(root, {**rec, "head": None})  # legacy record with an unknown head
    path = _write(tmp_path / "ev.jsonl", _ev())
    assert _st(root, "--drain-events", str(path)) == cli.OK
    eph.write(root, {**eph.read(root, rec["name"]), "state": eph.DONE})
    assert _st(root, "--drain-events", str(path)) == cli.OK
    assert len(launched) == 2                      # it was held back, not dropped
    assert [r["outcome"] for r in pe.settled(root).values()] == ["admitted"]


def test_a_job_on_another_pr_or_of_another_kind_does_not_hold_the_event(store, tmp_path, monkeypatch, capsys):
    # The inverse: occupied() must be able to say no, or the drain stalls.
    root, _panes, launched = store
    monkeypatch.setattr(eph, "kick_drain", lambda r: None)
    # Another item: aegis-bmu3 would refuse a second task on it-1 by itself,
    # and that refusal would hide whether occupied() held the event back.
    _hand_spawn(root, pr=8, item="it-2")           # holds the one slot
    assert _st(root, "--ephemeral", "--job", "review", "--item", "it-1", "--repo", "o/n",
               "--pr", "7", "--head", HEAD) == cli.OK          # queued as a ticket
    capsys.readouterr()
    assert _st(root, "--drain-events", str(_write(tmp_path / "ev.jsonl", _ev()))) == cli.OK
    assert "  deferred " not in capsys.readouterr().out
    assert [r["outcome"] for r in pe.settled(root).values()] == ["admitted"]
    assert len(launched) + len(eph.tickets(root)) == 3


def test_occupied_matches_exact_heads_and_holds_head_less_ones():
    ev = pe.parse(json.dumps(_ev(job="merge", head=NEWER)))
    exact = {"name": "eph-merge-x", "job": "merge", "repo": "o/n", "pr": 7, "head": NEWER}
    other_head = {**exact, "name": "eph-merge-old", "head": HEAD}
    head_less = {**exact, "name": "eph-merge-hl", "head": None}
    assert pe.occupied(ev, [other_head], []) is None
    assert pe.occupied(ev, [other_head, head_less], []) == ("eph-merge-hl", False)
    assert pe.occupied(ev, [head_less, exact], []) == ("eph-merge-x", True)
    assert pe.occupied(ev, [], [{"id": "q-1", "job": "merge", "repo": "o/n", "pr": 7}]) == ("q-1", False)
    assert pe.occupied(ev, [{**exact, "repo": "o/other"}], []) is None


@pytest.mark.parametrize("job", ["review", "task"])
def test_a_hand_spawn_without_head_keeps_the_forge_head(store, tmp_path, monkeypatch, job):
    root, _panes, launched = store
    _forge(monkeypatch)
    assert _st(root, "--ephemeral", "--job", job, "--item", "it-1",
               "--repo", "o/n", "--pr", "7", "--harness", "claude") == cli.OK
    (rec,) = eph.live(root)
    assert rec["head"] == HEAD
    path = _write(tmp_path / "ev.jsonl", _ev(job=job))
    assert _st(root, "--drain-events", str(path)) == cli.OK
    eph.write(root, {**rec, "state": eph.DONE})
    assert _st(root, "--drain-events", str(path)) == cli.OK
    assert len(launched) == 1


def test_a_launching_hand_spawn_defers_until_launch_succeeds_or_fails(store, tmp_path):
    root, _panes, launched = store
    rec = _hand_spawn(root, job="merge")
    eph.write(root, {**rec, "state": eph.LAUNCHING})
    path = _write(tmp_path / "ev.jsonl", _ev(job="merge"))
    assert _st(root, "--drain-events", str(path)) == cli.OK
    assert pe.settled(root) == {}
    eph.write(root, {**rec, "state": eph.DONE, "verdict": "failed"})
    assert _st(root, "--drain-events", str(path)) == cli.OK
    assert len(launched) == 2


@pytest.mark.parametrize("head", [None, {}, {"sha": "bad"}, "malformed"])
def test_an_unproved_forge_head_stays_unknown(store, monkeypatch, head):
    root, _panes, _launched = store
    _forge(monkeypatch, head=head)
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1",
               "--repo", "o/n", "--pr", "7") == cli.OK
    (rec,) = eph.live(root)
    assert rec["head"] is None
    assert pe.occupied(_ev(), [rec], []) == (rec["name"], False)


def test_launching_is_not_crash_recovery_proof():
    rec = {"name": "eph-review-x", "job": "review", "repo": "o/n", "pr": 7,
           "head": HEAD, "state": eph.LAUNCHING, "spawned_at": 101.0}
    assert pe.in_flight(_ev(job="review"), [rec], [], since=100.0) is None
    assert pe.occupied(_ev(job="review"), [rec], []) == (rec["name"], False)
    rec["state"] = eph.LIVE
    assert pe.in_flight(_ev(job="review"), [rec], [], since=100.0) == rec["name"]


@pytest.mark.parametrize("job", ["review", "task"])
def test_a_queued_hand_spawn_keeps_the_head_and_settles_its_event(store, tmp_path, monkeypatch, job):
    root, _panes, launched = store
    monkeypatch.setattr(eph, "kick_drain", lambda r: None)
    _hand_spawn(root, item="it-2", pr=8)
    assert _st(root, "--ephemeral", "--job", job, "--item", "it-1",
               "--repo", "o/n", "--pr", "7", "--head", HEAD) == cli.OK
    (ticket,) = eph.tickets(root)
    assert ticket["head"] == HEAD
    path = _write(tmp_path / "ev.jsonl", _ev(job=job))
    assert _st(root, "--drain-events", str(path)) == cli.OK
    assert len(launched) == 1 and len(eph.tickets(root)) == 1
    assert pe.settled(root)[_ev(job=job)["event_id"]]["outcome"] == "admitted"
