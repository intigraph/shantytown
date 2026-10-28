"""stop_policy rank 2a — the administrator's own P0 plate (aegis-c01c.1).

Stiwi: "you keep stopping when there is much work to do". Measured: with the one
crew member busy, Rule Zero allowed the administrator's stop over ~10 unstarted
P0s, because it only ever looked at (free crew) x (unassigned ready work). Rank
2a blocks when a READY P0 nobody is working on meets capacity to start it, and
blocks ONCE per unchanged state so it cannot loop.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from shantytown import stop_policy as sp
from shantytown.answer import Answer
from shantytown.config import Fleet, Hibernate
from shantytown.events import StopEvent
from shantytown.tier import Reason


def _p0(n, owner="hammond", title=None):
    return sp.P0Item(id=f"aegis-p{n}", title=title or f"item {n}", owner=owner)


def _inp(**kw):
    base = dict(me="hammond", role="administrator")
    base.update(kw)
    return sp.Inputs(**base)


SELF = sp.Capacity(self_slots=1)
EPH = sp.Capacity(ephemeral_slots=2)


# --- the defect: busy crew, unstarted P0s, the administrator stops ----------

def test_own_ready_p0_with_a_free_self_slot_blocks_and_names_the_top_items():
    v = sp.decide(_inp(p0_plate=[_p0(1), _p0(2), _p0(3), _p0(4), _p0(5)],
                       capacity=SELF))
    assert v.block and v.by == sp.BY_P0_PLATE
    assert "5 ready P0 item(s)" in v.reason
    # Plate order IS seeds priority+rank order; the reason names the top three.
    assert "aegis-p1 (item 1), aegis-p2 (item 2), aegis-p3 (item 3)" in v.reason
    assert "(+2 more)" in v.reason and "aegis-p4" not in v.reason
    assert "1 free slot(s) of your own" in v.reason


def test_unassigned_p0_with_free_ephemeral_slots_blocks():
    """The aegis-c01c.2 plug: slots arrive as a number, not a new rank."""
    v = sp.decide(_inp(p0_plate=[_p0(1, owner="")], capacity=EPH))
    assert v.block and v.by == sp.BY_P0_PLATE
    assert "2 free ephemeral slot(s)" in v.reason


def test_unassigned_p0_with_a_free_crew_member_blocks_when_rule_zero_did_not():
    """e.g. the crew member is free but the item is assigned-to-nobody P0 that
    Rule Zero's count missed — rank 2a still names it."""
    v = sp.decide(_inp(p0_plate=[_p0(1, owner="")],
                       capacity=sp.Capacity(free_crew=("lex",))))
    assert v.block and v.by == sp.BY_P0_PLATE and "free crew: lex" in v.reason


def test_the_coordinator_is_not_told_to_execute_unassigned_work_itself():
    v = sp.decide(_inp(p0_plate=[_p0(1, owner="")], capacity=SELF))
    assert not v.block and v.by == sp.BY_NOTHING


def test_no_capacity_allows():
    """In-flight work fills the self slots (self_slots=0), crew busy, no
    ephemeral slots: idle is correct."""
    v = sp.decide(_inp(p0_plate=[_p0(1), _p0(2, owner="")],
                       capacity=sp.Capacity()))
    assert not v.block and v.by == sp.BY_NOTHING


def test_empty_plate_allows():
    v = sp.decide(_inp(capacity=sp.Capacity(free_crew=("lex",),
                                            ephemeral_slots=3, self_slots=1)))
    assert not v.block and v.by == sp.BY_NOTHING


def test_a_worker_never_gets_rank_2a():
    v = sp.decide(_inp(role="worker", p0_plate=[_p0(1)], capacity=SELF))
    assert not v.block


# --- no loop ------------------------------------------------------------------

def test_the_same_state_never_blocks_twice():
    inp = _inp(p0_plate=[_p0(1), _p0(2)], capacity=SELF)
    first = sp.decide(inp)
    assert first.block
    inp.p0_last = sp.p0_ledger_update(inp, first)
    second = sp.decide(inp)
    assert not second.block and second.by == sp.BY_P0_UNCHANGED
    assert "aegis-p1" in second.reason, "the allow still names what waits"
    assert sp.p0_ledger_update(inp, second) == inp.p0_last


def test_plate_order_does_not_count_as_a_change():
    a = _inp(p0_plate=[_p0(1), _p0(2)], capacity=SELF)
    b = _inp(p0_plate=[_p0(2), _p0(1)], capacity=SELF)
    assert sp.p0_state(a) == sp.p0_state(b)


def test_a_changed_plate_or_capacity_re_arms_the_block():
    inp = _inp(p0_plate=[_p0(1)], capacity=SELF)
    last = sp.p0_state(inp)
    grown = _inp(p0_plate=[_p0(1), _p0(2)], capacity=SELF, p0_last=last)
    assert sp.decide(grown).block
    freed = _inp(p0_plate=[_p0(1)], p0_last=last,
                 capacity=sp.Capacity(self_slots=2))
    assert sp.decide(freed).block


def test_ledger_untouched_when_a_higher_rank_decided_first():
    """Rank 2a never looked, so the state must not be marked seen — otherwise
    the first real look would be suppressed as 'unchanged'."""
    inp = _inp(pending=[StopEvent(id="e", to="hammond", frm="lex",
                                  reason=Reason.UNTRACKED_WORK.value)],
               p0_plate=[_p0(1)], capacity=SELF)
    v = sp.decide(inp)
    assert v.by == sp.BY_URGENT
    assert sp.p0_ledger_update(inp, v) is None


def test_ledger_clears_when_nothing_is_startable():
    """Plate emptied then refilled with the same item is a NEW state."""
    inp = _inp(p0_plate=[_p0(1)], capacity=sp.Capacity(), p0_last="x")
    assert sp.p0_ledger_update(inp, sp.decide(inp)) == ""


def test_p0_ledger_round_trips_and_reads_missing_as_never(tmp_path):
    led = sp.P0Ledger(tmp_path)
    assert led.last("hammond") is None
    led.record("hammond", "aegis-p1|crew=|eph=0|self=1")
    assert led.last("hammond") == "aegis-p1|crew=|eph=0|self=1"
    (tmp_path / "stop-policy" / "hammond.p0.json").write_text("{not json")
    assert led.last("hammond") is None, "a corrupt ledger costs one extra block"


# --- ordering against the other ranks ---------------------------------------

def test_urgent_outranks_rank_2a():
    v = sp.decide(_inp(pending=[StopEvent(id="e", to="hammond", frm="lex",
                                          reason=None, rose=True)],
                       p0_plate=[_p0(1)], capacity=SELF))
    assert v.block and v.by == sp.BY_URGENT


def test_rule_zero_outranks_rank_2a():
    v = sp.decide(_inp(free_feedable=["lex"], dispatchable=3,
                       p0_plate=[_p0(1)],
                       capacity=sp.Capacity(free_crew=("lex",), self_slots=1)))
    assert v.block and v.by == sp.BY_RULE_ZERO


def test_admin_wake_budget_enforce_outranks_rank_2a():
    v = sp.decide(_inp(admin_wake_mode="enforce", admin_usage_pct=95.0,
                       admin_wake_elapsed=10.0,
                       p0_plate=[_p0(1)], capacity=SELF))
    assert not v.block and v.by == sp.BY_ADMIN_BUDGET


def test_stood_down_yields_loudly():
    v = sp.decide(_inp(fleet=Fleet(stood_down=True),
                       p0_plate=[_p0(1)], capacity=SELF))
    assert not v.block and v.by == sp.BY_STOOD_DOWN
    assert "STOOD DOWN" in v.reason and "P0" in v.reason


def test_over_capacity_yields_loudly():
    v = sp.decide(_inp(fleet=Fleet(max_load_per_core=2.0), load_per_core=5.0,
                       p0_plate=[_p0(1)], capacity=SELF))
    assert not v.block and v.by == sp.BY_STOOD_DOWN
    assert "saturated" in v.reason


def test_rank_2a_overrides_hibernate_and_says_so():
    v = sp.decide(_inp(pending=[StopEvent(id="e", to="hammond", frm="lex")],
                       hibernate=Hibernate(enabled=True, max_quiet_minutes=60),
                       minutes_quiet=1.0, p0_plate=[_p0(1)], capacity=SELF))
    assert v.block and v.by == sp.BY_P0_PLATE and "OVERRIDDEN" in v.reason


def test_an_unchanged_plate_does_not_swallow_event_delivery():
    """The unchanged half falls THROUGH: a deliverable report below still
    blocks, and the ledger keeps the plate state so the NEXT stop still does
    not re-block on the plate."""
    inp = _inp(pending=[StopEvent(id="e", to="hammond", frm="lex")],
               p0_plate=[_p0(1)], capacity=SELF)
    inp.p0_last = sp.p0_state(inp)
    v = sp.decide(inp)
    assert v.block and v.by == sp.BY_EVENTS
    assert sp.p0_ledger_update(inp, v) == inp.p0_last


def test_an_unchanged_plate_lets_hibernate_sleep():
    inp = _inp(pending=[StopEvent(id="e", to="hammond", frm="lex")],
               hibernate=Hibernate(enabled=True, max_quiet_minutes=60),
               minutes_quiet=1.0, p0_plate=[_p0(1)], capacity=SELF)
    inp.p0_last = sp.p0_state(inp)
    assert sp.decide(inp).by == sp.BY_HIBERNATE


def test_governor_held_p0s_reach_rank_5_loudly():
    v = sp.decide(_inp(p0_held=2, capacity=EPH,
                       throttled_why="tier 90%: P0 only"))
    assert not v.block and v.by == sp.BY_THROTTLED
    assert "2 ready item(s)" in v.reason


# --- the plate reader (pure over tracker rows) -------------------------------

NOW = datetime(2026, 10, 28, 4, 0, tzinfo=timezone.utc)


def _row(i, prio=0, owner="", **kw):
    row = dict(id=f"aegis-{i}", title=f"t{i}", priority=prio, status="open",
               assignee=owner, created_at=f"2026-10-0{i % 9 + 1}T00:00:00Z")
    row.update(kw)
    return row


def test_plate_keeps_ready_unworked_p0s_in_priority_rank_order():
    ready = [_row(1, rank="20"), _row(2, rank="10"), _row(3, owner="hammond"),
             _row(4, prio=1), _row(5, owner="lex")]
    plate, in_flight, held = sp.p0_plate(ready, [], "hammond", now=NOW)
    assert [i.id for i in plate] == ["aegis-2", "aegis-1", "aegis-3"]
    assert plate[2].owner == "hammond" and plate[0].owner == ""
    assert (in_flight, held) == (0, 0)


def test_plate_excludes_what_rule_zero_excludes():
    ready = [_row(1, issue_type="epic"), _row(2, labels=["decision-needed"]),
             _row(3, labels=["feed:manual"]), _row(4, title="inbox: hi"),
             _row(5, defer_until="2026-10-29T00:00:00Z"),
             _row(6, defer_until="2026-10-27T00:00:00Z"),
             _row(7, owner="hammond", labels=["parked:wait"])]
    plate, _, _ = sp.p0_plate(ready, [], "hammond", now=NOW)
    assert [i.id for i in plate] == ["aegis-6"]


def test_my_in_progress_items_are_in_flight_occupancy():
    active = [_row(8, owner="hammond", status="in_progress"),
              _row(9, owner="beads/crew/hammond", status="in_progress"),
              _row(10, owner="lex", status="in_progress")]
    _, in_flight, _ = sp.p0_plate([], active, "hammond", now=NOW)
    assert in_flight == 2


def test_governor_floor_holds_unassigned_but_not_my_own():
    refuse = lambda item: "floor P0 refused"   # noqa: E731
    plate, _, held = sp.p0_plate([_row(1), _row(2, owner="hammond")], [],
                                 "hammond", admits=refuse, now=NOW)
    assert [i.id for i in plate] == ["aegis-2"] and held == 1


# --- gathering: capacity sources and fail-open -------------------------------

class _Reg:
    def get(self, n):
        from shantytown.protocols import Agent
        return Agent(name=n, role="administrator", pane="p")

    def all(self):
        return Answer.complete_read([self.get("hammond")], how="test registry")


class _Events:
    def pending(self, me):
        return []


def _gate(monkeypatch, free=()):
    from shantytown import feed_check as feed_mod
    # The host's real load must not decide these tests.
    monkeypatch.setattr(sp, "_load_per_core", lambda: 0.0)
    monkeypatch.setattr(feed_mod, "gate_inputs",
                        lambda *a, **k: (list(free), 0, []))
    monkeypatch.setattr(feed_mod, "governor_admits", lambda root: None)


def test_gather_counts_self_slots_minus_in_flight(tmp_path, monkeypatch):
    _gate(monkeypatch)
    (tmp_path / "shantytown.toml").write_text("[fleet]\nmax_load_per_core = 0\nadmin_self_slots = 2\n")
    reader = lambda: ([_row(1, owner="hammond")],          # noqa: E731
                      [_row(2, owner="hammond", status="in_progress")])
    inp = sp.gather(tmp_path, "hammond", reg=_Reg(), panes=object(),
                    runtime=object(), events=_Events(), p0_reader=reader)
    assert inp.capacity.self_slots == 1
    assert [i.id for i in inp.p0_plate] == ["aegis-1"]
    assert sp.decide(inp).by == sp.BY_P0_PLATE


def test_gather_skips_the_board_read_when_no_capacity_is_possible(tmp_path, monkeypatch):
    _gate(monkeypatch)
    (tmp_path / "shantytown.toml").write_text("[fleet]\nadmin_self_slots = 0\n")

    def reader():
        raise AssertionError("read the board with zero possible capacity")

    inp = sp.gather(tmp_path, "hammond", reg=_Reg(), panes=object(),
                    runtime=object(), events=_Events(), p0_reader=reader)
    assert inp.p0_plate == [] and not sp.decide(inp).block


def test_a_broken_plate_read_fails_open_loudly(tmp_path, monkeypatch, capsys):
    _gate(monkeypatch)

    def reader():
        raise RuntimeError("seeds unreachable")

    inp = sp.gather(tmp_path, "hammond", reg=_Reg(), panes=object(),
                    runtime=object(), events=_Events(), p0_reader=reader)
    assert inp.p0_plate == [] and not sp.decide(inp).block
    assert "P0-plate read FAILED" in capsys.readouterr().err


def test_live_ephemeral_jobs_use_up_slots(tmp_path):
    """The module landed (aegis-c01c.2): slots are the cap minus live jobs."""
    from shantytown import ephemeral
    (tmp_path / "shantytown.toml").write_text("[ephemeral]\nmax_agents = 1\n")
    assert sp.ephemeral_free_slots(tmp_path) == 1
    ephemeral.write(tmp_path, {"name": "eph-task-abcdef", "state": ephemeral.LIVE})
    assert sp.ephemeral_free_slots(tmp_path) == 0


def test_ephemeral_slots_plug_in(tmp_path, monkeypatch):
    from shantytown import ephemeral
    # aegis-c01c.2 landed the real plug: the cap minus live jobs.
    assert sp.ephemeral_free_slots(tmp_path) == 2           # default max_agents
    (tmp_path / "shantytown.toml").write_text("[ephemeral]\nmax_agents = 0\n")
    assert sp.ephemeral_free_slots(tmp_path) == 0
    monkeypatch.setattr(ephemeral, "free_slots", lambda root: 3)
    assert sp.ephemeral_free_slots(tmp_path) == 3
    monkeypatch.setattr(ephemeral, "free_slots",
                        lambda root: (_ for _ in ()).throw(OSError("x")))
    assert sp.ephemeral_free_slots(tmp_path) == 0


def test_run_blocks_once_then_allows_the_same_state(tmp_path, monkeypatch, capsys):
    """End to end through the ledger: the loop guard holds across stops."""
    _gate(monkeypatch)
    monkeypatch.setattr(sp, "_drain_payload", lambda *a: "")
    monkeypatch.setattr(sp, "_own_context_line", lambda *a: "")
    reader = lambda: ([_row(1, owner="hammond")], [])       # noqa: E731
    kw = dict(reg=_Reg(), panes=object(), runtime=object(), events=_Events(),
              p0_reader=reader, wake_log=_NoLog())
    sp.run(tmp_path, "hammond", **kw)
    first = capsys.readouterr()
    assert json.loads(first.out)["decision"] == "block"
    assert "aegis-1" in json.loads(first.out)["reason"]
    sp.run(tmp_path, "hammond", **kw)
    second = capsys.readouterr()
    assert second.out == "" and "p0-plate-unchanged" in second.err


class _NoLog:
    def record_wake(self, *a):
        pass

    def last(self, *a):
        return None

    def minutes_since(self, *a):
        return None


def test_config_refuses_a_bad_self_slot_count(tmp_path):
    from shantytown import config
    (tmp_path / "shantytown.toml").write_text("[fleet]\nadmin_self_slots = -1\n")
    _cfg, err = config.load_or_default(tmp_path)
    assert err and "admin_self_slots" in str(err)


# --- review follow-ups: host, supervised jobs, one snapshot -------------------

def _host_config(root):
    (root / "shantytown.toml").write_text(
        '[host]\nname = "local"\n'
        '[host.peers.remote]\nssh = "remote"\nroot = "/crew"\n')


def test_peer_label_does_not_block_here_but_unlabelled_work_does(tmp_path, monkeypatch):
    _gate(monkeypatch)
    _host_config(tmp_path)
    for labels, expected in [(["remote"], False), ([], True), (["unrelated"], True),
                             (["local"], True)]:
        inp = sp.gather(tmp_path, "hammond", reg=_Reg(), panes=object(),
                        runtime=object(), events=_Events(),
                        p0_reader=lambda: ([_row(1, owner="hammond", labels=labels)], []))
        assert sp.decide(inp).block is expected


def test_offhost_assignee_card_is_not_startable(tmp_path, monkeypatch):
    from shantytown.protocols import Agent
    _gate(monkeypatch)
    _host_config(tmp_path)

    class Reg(_Reg):
        def get(self, name):
            return Agent(name=name, role="administrator", pane="p", host="remote")

    inp = sp.gather(tmp_path, "hammond", reg=Reg(), panes=object(),
                    runtime=object(), events=_Events(),
                    p0_reader=lambda: ([_row(1, owner="crew/hammond")], []))
    assert inp.p0_plate == [] and not sp.decide(inp).block


def test_live_job_holds_item_until_teardown_including_retry(tmp_path, monkeypatch):
    from shantytown import ephemeral
    _gate(monkeypatch)
    (tmp_path / "shantytown.toml").write_text('[ephemeral]\nmax_agents = 3\n')
    name = "eph-task-abcdef"
    for state in (ephemeral.LAUNCHING, ephemeral.LIVE, ephemeral.ENDING, ephemeral.DONE):
        ephemeral.write(tmp_path, {"name": name, "state": state, "item": "aegis-1"})
        inp = sp.gather(tmp_path, "hammond", reg=_Reg(), panes=object(),
                        runtime=object(), events=_Events(),
                        p0_reader=lambda: ([_row(1), _row(2)], []))
        assert [i.id for i in inp.p0_plate] == (
            ["aegis-1", "aegis-2"] if state == ephemeral.DONE else ["aegis-2"])
    ephemeral.write(tmp_path, {"name": "eph-task-fedcba", "state": ephemeral.LIVE,
                               "item": "aegis-1"})
    inp = sp.gather(tmp_path, "hammond", reg=_Reg(), panes=object(),
                    runtime=object(), events=_Events(),
                    p0_reader=lambda: ([_row(1)], []))
    assert inp.p0_plate == [] and not sp.decide(inp).block


def test_own_only_plate_ignores_crew_and_ephemeral_capacity_churn():
    inp = _inp(p0_plate=[_p0(1)], capacity=SELF)
    inp.p0_last = sp.p0_state(inp)
    inp.capacity = sp.Capacity(self_slots=1, free_crew=("lex",), ephemeral_slots=3)
    assert sp.decide(inp).by == sp.BY_P0_UNCHANGED


def test_unassigned_only_plate_ignores_self_capacity_churn():
    inp = _inp(p0_plate=[_p0(1, owner="")], capacity=EPH)
    inp.p0_last = sp.p0_state(inp)
    inp.capacity = sp.Capacity(self_slots=4, ephemeral_slots=2)
    assert sp.decide(inp).by == sp.BY_P0_UNCHANGED


def test_held_message_counts_each_item_once():
    inp = _inp(free_feedable=["lex"], throttled=2, p0_held=2,
               throttled_ids={"shared", "ordinary"}, p0_held_ids={"shared", "p0"})
    verdict = sp.decide(inp)
    assert verdict.by == sp.BY_THROTTLED and "3 ready item(s)" in verdict.reason


def test_rule_zero_and_plate_share_one_scoped_board_read(tmp_path, monkeypatch):
    from shantytown import feed_check
    # Use the real gate: only pane/usage measurements are synthetic.
    monkeypatch.setattr(sp, "_load_per_core", lambda: 0.0)
    monkeypatch.setattr(feed_check, "free_feedable_workers", lambda *a, **k: ["lex"])
    monkeypatch.setattr(feed_check, "worker_governor_admissions",
                        lambda *a: {"lex": lambda item: "floor"})
    monkeypatch.setattr(feed_check, "governor_admits", lambda root: lambda item: "floor")
    reads = []

    def read(root, reg, *, owners):
        reads.append(owners)
        assert len(reads) == 1, "second board read"
        return [_row(1), _row(2, owner="hammond")], []

    monkeypatch.setattr(feed_check, "queue_state", read)
    inp = sp.gather(tmp_path, "hammond", reg=_Reg(), panes=object(),
                    runtime=object(), events=_Events())
    assert reads == [["hammond", "lex"]]
    assert [i.id for i in inp.p0_plate] == ["aegis-2"]
    assert inp.throttled_ids == inp.p0_held_ids == {"aegis-1"}



def test_local_assignee_card_stays_startable(tmp_path, monkeypatch):
    from shantytown.protocols import Agent
    _gate(monkeypatch)
    _host_config(tmp_path)

    class Reg(_Reg):
        def get(self, name):
            return Agent(name=name, role="administrator", pane="p", host="local")

    inp = sp.gather(tmp_path, "hammond", reg=Reg(), panes=object(),
                    runtime=object(), events=_Events(),
                    p0_reader=lambda: ([_row(1, owner="hammond")], []))
    assert sp.decide(inp).block
