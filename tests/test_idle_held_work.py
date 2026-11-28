"""Idle crew holding READY work is told, and a stalled lead is raised (aegis-0dh5).

MEASURED 2026-11-27: lead ellie sat idle for about 56 minutes with ready work.
`st crew` showed her "stalled" and nothing acted on it. Part B: a lead that
stops idle holding ready items is woken at that stop with every held id named.
Part C: a lead stalled past the threshold with ready held work raises one
notice per episode to the administrator, and a stall with no ready work
raises nothing. Each check here is also shown saying no.
"""
from __future__ import annotations

import json

from shantytown import stop_event
from shantytown.answer import Answer
from shantytown.notify import LeadStallAlerter
from shantytown.protocols import Agent


class _Reg:
    def __init__(self, cards):
        self._c = {a.name: a for a in cards}

    def get(self, name):
        return self._c[name]

    def all(self):
        return Answer.complete_read(list(self._c.values()), how="test registry")


class _Panes:
    def __init__(self, screens):
        self.screens = screens
        self.sent = []

    def exists(self, pane):
        return pane in self.screens

    def capture(self, pane, history=0, attrs=False):
        return self.screens.get(pane, "")

    def send(self, pane, text):
        self.sent.append((pane, text))


class _Runtime:
    def shows_ready_ui(self, screen):
        return "shift+tab" in screen

    def awaiting_answer(self, screen):
        return False


IDLE = "❯ \n  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents"
BUSY = "✻ Working… (12s · esc to interrupt)\n" + IDLE
LEAD = Agent(name="ellie", role="lead", pane="p-e")
ADMIN = Agent(name="sattler", role="administrator", pane="p-s")


# --- B: the stop-time wake names every held ready item ----------------------

def _stop(monkeypatch, capsys, ready, claims):
    def fake(args, cwd, **kw):
        if args[0] == "ready":
            return ready
        if args[0] == "list":
            return []
        if args[0] == "update":
            claims.append(args[1])
            return []
        raise AssertionError(args)
    monkeypatch.setattr(stop_event, "_bd_json", fake)
    stop_event._haul(_Reg([LEAD]), _Panes({"p-e": "❯ "}), "ellie", None)
    out = capsys.readouterr().out.strip()
    return [json.loads(line) for line in out.splitlines() if line]


def test_lead_stopping_idle_with_two_ready_items_gets_one_wake_naming_both(
        monkeypatch, capsys):
    claims = []
    ready = [{"id": "aegis-a1", "title": "first", "assignee": "crew/ellie"},
             {"id": "aegis-a2", "title": "second", "assignee": "crew/ellie"}]
    blocks = _stop(monkeypatch, capsys, ready, claims)
    assert len(blocks) == 1
    reason = blocks[0]["reason"]
    assert blocks[0]["decision"] == "block"
    assert reason.startswith("you hold 2 ready item(s): aegis-a1, aegis-a2")
    assert claims == ["aegis-a1"]


def test_lead_stopping_idle_holding_nothing_ready_gets_no_wake(monkeypatch, capsys):
    claims = []
    other = [{"id": "aegis-z9", "assignee": "crew/kelly"}]
    assert _stop(monkeypatch, capsys, other, claims) == []
    assert claims == []


# --- C: a stalled lead with ready held work raises one notice ----------------

def _world(tmp_path, *, screen=IDLE, active=None, ready=None, jobs=(),
           verdict_for=None):
    reg = _Reg([ADMIN, LEAD])
    panes = _Panes({"p-s": "", "p-e": screen})
    clock = {"t": 1000.0}
    pushed = []

    def push(reg, panes, message):
        pushed.append(message)
        return "sattler"

    active = [{"id": "aegis-gqi0", "assignee": "crew/ellie"}] if active is None else active
    ready = ([{"id": "aegis-8fye.9", "assignee": "crew/ellie"},
              {"id": "aegis-r2", "assignee": "crew/ellie"}] if ready is None else ready)
    mk = lambda: LeadStallAlerter(tmp_path, reg, panes, _Runtime(), push=push,
                                  in_progress=lambda: active, ready=lambda: ready,
                                  live_jobs=lambda: list(jobs), threshold_min=15,
                                  now=lambda: clock["t"], log=lambda m: None,
                                  verdict_for=verdict_for)
    return reg, clock, pushed, mk


def test_stalled_lead_with_ready_work_raises_exactly_one_notice(tmp_path):
    reg, clock, pushed, mk = _world(tmp_path)
    agents = reg.all().exact()
    assert mk().sweep(agents) == []                  # the episode starts
    clock["t"] += 10 * 60
    assert mk().sweep(agents) == []                  # under the threshold
    clock["t"] += 6 * 60
    assert mk().sweep(agents) == ["ellie"]
    clock["t"] += 30 * 60
    assert mk().sweep(agents) == []                  # one notice per episode
    (msg,) = pushed
    assert "ellie" in msg and "aegis-8fye.9, aegis-r2" in msg and "aegis-gqi0" in msg


def test_stall_with_no_ready_work_raises_nothing(tmp_path):
    reg, clock, pushed, mk = _world(tmp_path, ready=[])
    agents = reg.all().exact()
    mk().sweep(agents)
    clock["t"] += 60 * 60
    assert mk().sweep(agents) == [] and pushed == []


def test_a_working_lead_is_not_stalled(tmp_path):
    reg, clock, pushed, mk = _world(tmp_path, screen=BUSY)
    agents = reg.all().exact()
    mk().sweep(agents)
    clock["t"] += 60 * 60
    assert mk().sweep(agents) == [] and pushed == []


def test_a_lead_waiting_on_its_own_live_job_is_not_stalled(tmp_path):
    reg, clock, pushed, mk = _world(tmp_path, jobs=[{"spawned_by": "ellie"}])
    agents = reg.all().exact()
    mk().sweep(agents)
    clock["t"] += 60 * 60
    assert mk().sweep(agents) == [] and pushed == []


def test_progress_ends_the_episode_and_a_new_stall_notices_again(tmp_path):
    reg, clock, pushed, mk = _world(tmp_path)
    agents = reg.all().exact()
    mk().sweep(agents)
    clock["t"] += 16 * 60
    assert mk().sweep(agents) == ["ellie"]
    reg_panes = mk()._panes
    reg_panes.screens["p-e"] = BUSY                  # she picks something up
    mk().sweep(agents)
    reg_panes.screens["p-e"] = IDLE
    mk().sweep(agents)
    clock["t"] += 16 * 60
    assert mk().sweep(agents) == ["ellie"]
    assert len(pushed) == 2


def test_unreachable_administrator_retries_instead_of_spending_the_notice(tmp_path):
    reg, clock, pushed, mk = _world(tmp_path)
    agents = reg.all().exact()
    mk().sweep(agents)
    clock["t"] += 16 * 60
    alerter = mk()
    alerter._push = lambda *a: None
    assert alerter.sweep(agents) == []
    assert mk().sweep(agents) == ["ellie"]


def test_read_failure_fails_open(tmp_path):
    reg, clock, pushed, mk = _world(tmp_path)
    alerter = mk()
    alerter._ready = lambda: (_ for _ in ()).throw(RuntimeError("tracker down"))
    assert alerter.sweep(reg.all().exact()) == [] and pushed == []


class _Verdict:
    """The surface feed_check.admitted_haul reads off a governor verdict."""
    admit_class = False

    def __init__(self, parked, excluded=""):
        self.parked = set(parked)
        self.excluded = excluded

    def excludes(self, agent, catalog=None):
        return self.excluded

    def admits(self, item, agent=None):
        return "media hold" if item.id in self.parked else ""

    def waives(self, item, agent=None):
        return False


def _stall_past_threshold(mk, clock, agents):
    mk().sweep(agents)
    clock["t"] += 16 * 60
    return mk().sweep(agents)


def test_a_lead_whose_held_work_is_all_parked_by_the_governor_is_not_raised(tmp_path):
    verdict = _Verdict({"aegis-8fye.9", "aegis-r2"})
    reg, clock, pushed, mk = _world(tmp_path, verdict_for=lambda card: verdict)
    assert _stall_past_threshold(mk, clock, reg.all().exact()) == []
    assert pushed == []


def test_only_governor_admitted_items_are_named_in_the_notice(tmp_path):
    verdict = _Verdict({"aegis-r2"})
    reg, clock, pushed, mk = _world(tmp_path, verdict_for=lambda card: verdict)
    assert _stall_past_threshold(mk, clock, reg.all().exact()) == ["ellie"]
    (msg,) = pushed
    assert "1 ready item(s): aegis-8fye.9." in msg and "aegis-r2" not in msg


def test_a_decision_labelled_anchor_is_parked_not_stalled(tmp_path):
    reg, clock, pushed, mk = _world(tmp_path, active=[
        {"id": "aegis-gqi0", "assignee": "crew/ellie", "labels": ["blocked-on-human"]}])
    assert _stall_past_threshold(mk, clock, reg.all().exact()) == []
    assert pushed == []


def test_an_episode_for_a_lead_that_left_the_roster_is_pruned(tmp_path):
    reg, clock, pushed, mk = _world(tmp_path)
    mk().sweep(reg.all().exact())
    alerter = mk()
    assert "ellie" in alerter._load()
    alerter.sweep([ADMIN])
    assert "ellie" not in mk()._load()


def test_a_lead_the_tier_excludes_by_role_is_not_raised(tmp_path):
    # A tier that stops the lead itself (not only its items): "Wake ellie"
    # would contradict it. The admitted control below shows the same world
    # does raise when the tier admits her.
    verdict = _Verdict(set(), excluded="quiet tier: ellie does not carry support")
    reg, clock, pushed, mk = _world(tmp_path, verdict_for=lambda card: verdict)
    assert _stall_past_threshold(mk, clock, reg.all().exact()) == []
    assert pushed == []
    verdict.excluded = ""
    assert _stall_past_threshold(mk, clock, reg.all().exact()) == ["ellie"]


class _BrokenPanes(_Panes):
    def capture(self, pane, history=0, attrs=False):
        if pane == "p-k":
            raise RuntimeError("pane vanished mid-capture")
        return super().capture(pane, history, attrs)


def test_a_failing_second_lead_does_not_repage_the_first(tmp_path):
    # Review of #798: one try around the whole loop returned before _save, so
    # lead A's `noticed` was lost whenever lead B raised, and A was re-paged
    # on every pass. B failing must cost only B.
    kelly = Agent(name="kelly", role="lead", pane="p-k")
    reg = _Reg([ADMIN, LEAD, kelly])
    panes = _BrokenPanes({"p-s": "", "p-e": IDLE, "p-k": IDLE})
    clock = {"t": 1000.0}
    pushed, logged = [], []
    active = [{"id": "aegis-gqi0", "assignee": "crew/ellie"},
              {"id": "aegis-k1", "assignee": "crew/kelly"}]
    ready = [{"id": "aegis-8fye.9", "assignee": "crew/ellie"},
             {"id": "aegis-k2", "assignee": "crew/kelly"}]
    mk = lambda: LeadStallAlerter(
        tmp_path, reg, panes, _Runtime(),
        push=lambda r, p, m: pushed.append(m) or "sattler",
        in_progress=lambda: active, ready=lambda: ready, live_jobs=lambda: [],
        threshold_min=15, now=lambda: clock["t"], log=logged.append)
    agents = reg.all().exact()
    mk().sweep(agents)
    clock["t"] += 16 * 60
    assert mk().sweep(agents) == ["ellie"]
    for _ in range(3):
        clock["t"] += 30 * 60
        assert mk().sweep(agents) == []
    assert len(pushed) == 1 and "kelly" not in pushed[0]
    assert any("kelly unreadable" in m for m in logged)


# --- tend wiring: the alerters are built the way _tend_once builds them -----

def _tend_alerter_calls():
    """Every `notify_mod.<Alerter>(...)` call inside cli._tend_once, by AST.

    Review of #798 at bed24818: tend passed `catalog=` to IdleFleetAlerter and
    StalledAlerter, which take no such keyword. The TypeError was swallowed by
    _sweep as "the stalled sweep CRASHED", silently disarming the worker stall
    self-heal and the idle-fleet alert, and no test constructs these the way
    tend does, so nothing went red.
    """
    import ast
    import inspect

    from shantytown import cli
    tree = ast.parse(inspect.getsource(cli._tend_once))
    calls = []
    for node in ast.walk(tree):
        f = getattr(node, "func", None)
        if (isinstance(node, ast.Call) and isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name) and f.value.id == "notify_mod"
                and f.attr[:1].isupper()):
            calls.append(node)
    return calls


def _unbindable(call):
    import ast
    import inspect

    from shantytown import notify
    if any(isinstance(a, ast.Starred) for a in call.args) or any(
            k.arg is None for k in call.keywords):
        return None                      # a splat cannot be checked statically
    sig = inspect.signature(getattr(notify, call.func.attr))
    try:
        sig.bind(*[None] * len(call.args),
                 **{k.arg: None for k in call.keywords})
    except TypeError as exc:
        return f"{call.func.attr} line {call.lineno}: {exc}"
    return None


def test_every_alerter_tend_builds_accepts_the_arguments_tend_passes():
    calls = _tend_alerter_calls()
    names = {c.func.attr for c in calls}
    # Vacuity guard: if the AST walk stops finding the calls, this test would
    # pass on anything.
    assert {"IdleFleetAlerter", "StalledAlerter", "LeadStallAlerter"} <= names
    bad = [m for m in map(_unbindable, calls) if m]
    assert bad == []


def test_the_wiring_check_says_no_to_an_unknown_keyword():
    import ast
    (call,) = [n for n in ast.walk(ast.parse(
        "notify_mod.StalledAlerter(r, g, p, t, log=l, verdict_for=v, catalog=c)"))
        if isinstance(n, ast.Call)]
    assert "catalog" in _unbindable(call)


def test_lead_stall_alerter_default_reads_are_the_tend_ones(tmp_path, monkeypatch):
    # Every other test injects in_progress/ready/live_jobs; tend does not, so
    # a wrong default would surface only as a swallowed CRASHED line.
    from shantytown import ephemeral, feed_check
    seen = {}

    def tend_active(root, reg, *, roles=None, owners=None):
        seen["active"] = (root, roles)
        return [{"id": "aegis-gqi0", "assignee": "crew/ellie"}]

    def tend_ready(root, reg, owners):
        seen["ready"] = (root, list(owners))
        return [{"id": "aegis-r2", "assignee": "crew/ellie"}]

    def live(root):
        seen["live"] = root
        return []

    monkeypatch.setattr(feed_check, "tend_active", tend_active)
    monkeypatch.setattr(feed_check, "tend_ready", tend_ready)
    monkeypatch.setattr(ephemeral, "live", live)
    reg = _Reg([ADMIN, LEAD])
    panes = _Panes({"p-s": "", "p-e": IDLE})
    clock = {"t": 1000.0}
    pushed = []
    mk = lambda: LeadStallAlerter(
        tmp_path, reg, panes, _Runtime(),
        push=lambda r, p, m: pushed.append(m) or "sattler",
        threshold_min=15, now=lambda: clock["t"])
    assert _stall_past_threshold(mk, clock, reg.all().exact()) == ["ellie"]
    assert seen == {"active": (tmp_path, ("lead",)),
                    "ready": (tmp_path, ["ellie"]), "live": tmp_path}
    assert len(pushed) == 1 and "aegis-r2" in pushed[0]
