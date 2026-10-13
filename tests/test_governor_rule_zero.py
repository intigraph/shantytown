"""Rule Zero and the usage governor must not contradict each other (aegis-diasw).

MEASURED IN PRODUCTION 2026-08-01, inside sixty seconds:

    st fleet tend -n   governor  usage 57% · 50% tier · dispatch only P1 and above
    st go <P2>   refused: the 50% tier is engaged and <bead> is P2
    feed_check   RULE ZERO — 1 feedable worker IDLE and 15 DISPATCHABLE beads.
                 Top ready: <P2>; <P2>; <P2>

A blocking stop hook ordered a dispatch the governor forbade, and named as its
top candidates the exact beads that would be refused. `dispatchable` meant "open,
unassigned, unblocked" and never asked whether the work could actually be sent.

These tests pin the two halves of the fix: feed_check asks the GOVERNOR'S OWN
resolver (never a second copy of the floor), and when a tier holds the whole
queue the stop is ALLOWED WITH A REASON — because "the throttle is holding" and
"the feeder is broken" were the same observation, and the coordinator acts on the
one it can act on.
"""
from __future__ import annotations

import pytest

from shantytown import feed_check as feed_mod
from shantytown import governor as gov_mod
from shantytown import stop_policy as sp


def _verdict(at: int, floor: int | None):
    """A governor Verdict with one engaged tier — the real object, so `admits`
    under test is the same code `st go` gates on."""
    tier = gov_mod.Tier(at=at, min_priority=floor)
    return gov_mod.Verdict(reading=gov_mod.Reading(), pct=float(at) + 7.0,
                           tier=tier, engaged=(tier,))


def _bead(bid: str, priority: int | None, assignee=None):
    return {"id": bid, "title": f"work {bid}", "priority": priority,
            "assignee": assignee, "labels": []}


# --- the floor comes FROM the governor --------------------------------------

def test_the_floor_is_the_governors_and_moves_when_the_tier_moves():
    """THE acceptance test, and it is written this way on purpose: the same beads
    are judged twice against two different tiers, and the verdict has to follow
    the tier. A duplicated constant in feed_check would pass one of these and
    fail the other — which is the only way to prove the floor is not copied."""
    beads = [_bead("a", 0), _bead("b", 1), _bead("c", 2), _bead("d", 3)]
    ready = [(b["id"], b["title"]) for b in beads]

    # 50% tier: P1 and above.
    ok, held = feed_mod.throttle(ready, beads, _verdict(50, 1).admits)
    assert [i[0] for i in ok] == ["a", "b"]
    assert [i[0] for i in held] == ["c", "d"]

    # 70% tier, stricter: P0 only. SAME beads, SAME call, different answer.
    ok, held = feed_mod.throttle(ready, beads, _verdict(70, 0).admits)
    assert [i[0] for i in ok] == ["a"]
    assert [i[0] for i in held] == ["b", "c", "d"]


def test_no_governor_configured_changes_nothing():
    """The default, and the one behaviour that must be bit-for-bit unchanged:
    with no [[governor.tier]] there is nothing to enforce and every bead is
    dispatchable exactly as before this feature existed."""
    beads = [_bead("a", 2), _bead("b", 4)]
    ready = [(b["id"], b["title"]) for b in beads]
    ok, held = feed_mod.throttle(ready, beads, None)
    assert ok == ready and held == []


def test_a_held_bead_carries_the_governors_own_words():
    """The refusal text is not re-written here. A reason composed by feed_check
    could disagree with the one `st go` prints for the same bead, and a
    coordinator reading two different explanations of one refusal is back to
    believing the mechanisms contradict each other."""
    beads = [_bead("c", 2)]
    _ok, held = feed_mod.throttle([("c", "work c")], beads, _verdict(50, 1).admits)
    assert "50% tier is engaged" in held[0][2] and "P2" in held[0][2]


def test_a_bead_with_no_priority_is_held_not_dispatched():
    """The governor already refuses an unprioritised item under a floor (it
    cannot be SHOWN to clear it). feed_check must not be more permissive than the
    thing that will refuse the dispatch, or the nag returns for that one bead."""
    beads = [_bead("z", None)]
    ok, held = feed_mod.throttle([("z", "work z")], beads, _verdict(50, 1).admits)
    assert ok == [] and len(held) == 1


def test_a_drain_tier_holds_everything_including_p0():
    """A full stop that still admitted a P0 would not be a full stop — and Rule
    Zero would nag for exactly that one bead, on a fleet that has been told to
    push its work and stop."""
    tier = gov_mod.Tier(at=95, action=gov_mod.DRAIN)
    v = gov_mod.Verdict(reading=gov_mod.Reading(), pct=96.0, tier=tier,
                        engaged=(tier,))
    ok, held = feed_mod.throttle([("a", "t")], [_bead("a", 0)], v.admits)
    assert ok == [] and len(held) == 1


# --- the stop decision ------------------------------------------------------

def _inputs(**kw):
    base = dict(me="sattler", role="administrator")
    base.update(kw)
    return sp.Inputs(**base)


def test_a_fully_throttled_queue_allows_the_stop_and_SAYS_WHY():
    """The bead's first acceptance criterion. Allowing is right; allowing
    SILENTLY is the defect — an idle fleet under an engaged tier is
    indistinguishable from a broken feeder, and the coordinator assumes the one
    it can act on."""
    v = sp.decide(_inputs(free_feedable=["tim"], dispatchable=0, throttled=15,
                          throttled_why="the usage governor's 50% tier is engaged"))
    assert v.block is False
    assert v.by == sp.BY_THROTTLED
    assert "IDLE IS CORRECT" in v.reason
    assert "15 ready item(s)" in v.reason
    assert "50% tier" in v.reason           # the tier, named


def test_a_p1_that_clears_the_floor_still_nags():
    """The second criterion, and the negative control for the first. A throttle
    that silenced Rule Zero whenever a tier was engaged would disable the gate
    for the entire high-usage window — which is when an idle fleet is most
    expensive."""
    v = sp.decide(_inputs(free_feedable=["tim"], dispatchable=1, throttled=14))
    assert v.block is True and v.by == sp.BY_RULE_ZERO


def test_no_tier_engaged_behaves_exactly_as_before():
    """The third criterion. throttled=0 is the ungoverned world."""
    assert sp.decide(_inputs(free_feedable=["tim"], dispatchable=3)).by == sp.BY_RULE_ZERO
    assert sp.decide(_inputs(free_feedable=[], dispatchable=0)).by == sp.BY_NOTHING


def test_the_throttled_allow_does_not_swallow_pending_events():
    """Ordering. A held queue is no reason to sit on somebody's undelivered
    report — rank 5 is deliberately BELOW the event ranks, so a throttle cannot
    become a way for the coordinator to stop hearing from its crew."""
    class _E:
        reason, rose = "worker-stop", False
    v = sp.decide(_inputs(free_feedable=["tim"], dispatchable=0, throttled=9,
                          pending=[_E()]))
    assert v.block is True and v.by == sp.BY_EVENTS


def test_the_throttle_never_invents_a_reason_to_block():
    """Nobody free -> nothing to say. A throttled queue with no idle worker is
    just a queue; announcing a capacity hold to an agent that could not have
    dispatched anything anyway is noise, and noise is what makes the real line
    get skipped."""
    v = sp.decide(_inputs(free_feedable=[], dispatchable=0, throttled=15))
    assert v.block is False and v.by == sp.BY_NOTHING


def test_hibernate_names_the_throttle_instead_of_bare_nothing_dispatchable():
    """'nothing dispatchable' is true and misleading when the queue is full: an
    operator reading it goes looking for an empty board and finds fifteen beads."""
    class _E:
        reason, rose = "worker-stop", False
    from shantytown.config import Hibernate
    v = sp.decide(_inputs(free_feedable=[], dispatchable=0, throttled=15,
                          pending=[_E()], hibernate=Hibernate(enabled=True),
                          minutes_quiet=1.0))
    assert v.by == sp.BY_HIBERNATE
    assert "held by the usage governor" in v.reason


# --- the escape hatch stays (ruled by Stiwi, decision 3 WITHDRAWN) ----------

def test_st_go_still_offers_the_priority_bump():
    """DECISION 3 WAS WITHDRAWN and this test is why it stays withdrawn: the
    hatch is legitimate BECAUSE the bump is recorded — bd history carries
    priority per revision with timestamps, so an inflation is visible and
    diffable after the fact.

    The defect was never that the hatch existed. It was that a BLOCKING stop hook
    herded the coordinator toward it while the governor forbade the dispatch.
    Removing the push (rank 5 above) is the fix; removing the hatch would have
    taken away a real operator affordance to solve a problem it did not cause.
    This test fails if someone 'helpfully' reinstates the reword."""
    class _I:
        id, priority = "aegis-x", 2
    why = _verdict(50, 1).admits(_I())
    assert "raise its priority" in why


def test_rule_zero_no_longer_recommends_beads_st_go_would_refuse():
    """The contradiction itself, end to end and in one assertion: the beads Rule
    Zero would have named as its top candidates are exactly the ones `st go`
    refuses, and after the fix it names none of them."""
    beads = [_bead("p2a", 2), _bead("p2b", 2), _bead("p2c", 2)]
    ready = [(b["id"], b["title"]) for b in beads]
    admits = _verdict(50, 1).admits

    ok, held = feed_mod.throttle(ready, beads, admits)
    assert ok == [], "not one of these may be recommended"
    # And every one of them would indeed have been refused at dispatch.
    for bid, _t, _w in held:
        assert admits(feed_mod._Item(next(b for b in beads if b["id"] == bid)))


# Mixed-harness advisories must use the dispatch lane, not the base subscription.
@pytest.fixture
def mixed_lanes(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from shantytown import cli, config
    from shantytown.protocols import Agent
    from shantytown.answer import Answer
    (tmp_path / 'shantytown.toml').write_text('[governor]\nsource="stub"\nstub_pct=83\n[[governor.tier]]\nat=70\nmin_priority=1\n[governor.by_harness.codex]\nsource="stub"\nstub_pct=10\n')
    cfg = config.load(tmp_path)
    governors = {
        name: gov_mod.Governor(policy, gov_mod.reader_for(policy),
                              gov_mod.FilesGovernorState(tmp_path, None if name == 'base' else name))
        for name, policy in [('base', cfg.governor),
                             ('codex', cfg.governor.by_harness['codex'])]
    }
    cards = [Agent(name='claude_worker', harness='claude'),
             Agent(name='codex_worker', harness='codex')]
    class Registry:
        def all(self):
            return Answer.complete_read(cards, how='paired harness fixture')
        def get(self, name):
            return next(card for card in cards if card.name == name)
    reg = Registry()
    monkeypatch.setattr(cli, '_governors', lambda a: (cfg, governors))
    monkeypatch.setattr(cli, '_registry', lambda a: reg)
    monkeypatch.setattr(feed_mod, 'queue_state', lambda *a, **kw: ([_bead('p2', 2)], []))
    return tmp_path, reg, cards, SimpleNamespace(root=tmp_path), governors


def test_codex_p2_feedable_while_claude_has_floor(mixed_lanes, monkeypatch):
    root, reg, cards, args, governors = mixed_lanes
    monkeypatch.setattr(feed_mod, 'free_feedable_workers',
                        lambda *a, **k: [card.name for card in cards])
    free, ready, held = feed_mod.gate_inputs(root, reg, None, None, 'coordinator')
    assert free == ['codex_worker']
    assert [row[0] for row in ready] == ['p2'] and held == []
    verdict = sp.decide(_inputs(free_feedable=free, dispatchable=len(ready)))
    assert verdict.block and verdict.by == sp.BY_RULE_ZERO
    assert 'codex_worker' in verdict.reason and 'claude_worker' not in verdict.reason


def test_claude_only_p2_is_still_held(mixed_lanes, monkeypatch):
    root, reg, cards, args, governors = mixed_lanes
    monkeypatch.setattr(feed_mod, 'free_feedable_workers',
                        lambda *a, **k: ['claude_worker'])
    free, ready, held = feed_mod.gate_inputs(root, reg, None, None, 'coordinator')
    assert free == ['claude_worker'] and ready == []
    assert len(held) == 1 and 'claude (claude_worker)' in held[0][2]
    verdict = sp.decide(_inputs(free_feedable=free, dispatchable=0,
                               throttled=1, throttled_why=held[0][2]))
    assert not verdict.block and 'claude (claude_worker)' in verdict.reason


def test_crew_warning_names_only_throttled_lane(mixed_lanes):
    from shantytown import cli
    root, reg, cards, args, governors = mixed_lanes
    note = cli._throttled_idle_note(args, [card.name for card in cards])
    assert 'THROTTLED-IDLE [claude: claude_worker]' in note
    assert 'P1' in note and 'codex_worker' not in note
    assert cli._throttled_idle_note(args, ['codex_worker']) == ''


def test_lanes_evaluated_once_and_never_persisted(mixed_lanes, monkeypatch):
    from shantytown import cli
    root, reg, cards, args, governors = mixed_lanes
    calls = []
    for name, governor in governors.items():
        old = governor.evaluate
        def evaluate(*, persist=True, old=old, name=name):
            calls.append((name, persist))
            return old(persist=persist)
        monkeypatch.setattr(governor, 'evaluate', evaluate)
    result = cli._governor_verdicts_for(args, [cards[0], cards[1], cards[0]])
    assert calls == [('base', False), ('codex', False)]
    assert len(result) == 2


def test_frozen_codex_lane_does_not_borrow_claude_headroom(mixed_lanes, monkeypatch):
    root, reg, cards, args, governors = mixed_lanes
    lost = gov_mod.Verdict(reading=gov_mod.Reading(), signal_lost=True, frozen=True)
    monkeypatch.setattr(governors['codex'], 'evaluate', lambda **kw: lost)
    monkeypatch.setattr(feed_mod, 'free_feedable_workers', lambda *a, **k: ['codex_worker'])
    free, ready, held = feed_mod.gate_inputs(root, reg, None, None)
    assert free == ['codex_worker'] and not ready and len(held) == 1
    assert 'codex (codex_worker)' in held[0][2]


def test_named_exemption_is_used_in_feed_and_advisory(mixed_lanes, monkeypatch):
    from dataclasses import replace
    from shantytown import cli
    root, reg, cards, args, governors = mixed_lanes
    governor = governors['base']
    verdict = replace(governor.evaluate(persist=False), exempt=('claude_worker',))
    monkeypatch.setattr(governor, 'evaluate', lambda **kw: verdict)
    monkeypatch.setattr(feed_mod, 'free_feedable_workers', lambda *a, **k: ['claude_worker'])
    free, ready, held = feed_mod.gate_inputs(root, reg, None, None)
    assert free == ['claude_worker'] and len(ready) == 1 and held == []
    assert cli._throttled_idle_note(args, free) == ''


def test_indeterminate_fleet_never_claims_a_readable_lane(mixed_lanes):
    from shantytown import cli
    from types import SimpleNamespace
    root, reg, cards, args, governors = mixed_lanes
    args._account_governor = SimpleNamespace(errors=['offline'], fallback=lambda: 'unknown fleet')
    with pytest.raises(RuntimeError, match='unknown fleet'):
        cli._governor_verdicts_for(args, cards)
