"""Routine stop wakes are bounded; urgent events never wait."""
from shantytown import stop_policy as sp
from shantytown.events import StopEvent


def inputs(mode="enforce", pct=85, elapsed=60, **kwargs):
    return sp.Inputs(me="admin", role="administrator", pending=[StopEvent(
        id="e", to="admin", frm="worker", reason=None, rose=False)],
        free_feedable=["worker"], dispatchable=1,
        admin_wake_mode=mode, admin_usage_pct=pct, admin_wake_elapsed=elapsed,
        **kwargs)


def test_explicit_budget_yields_rule_zero_without_consuming_events():
    inp = inputs()
    assert not sp.decide(inp).block
    assert len(inp.pending) == 1
    assert sp.decide(inp).by == "admin-wake-budget"


def test_default_off_and_advise_keep_original_dispatch():
    for mode in ("off", "advise"):
        assert sp.decide(inputs(mode=mode)).by == sp.BY_RULE_ZERO


def test_threshold_and_interval_edges():
    for pct, elapsed, expected in ((79.9, 0, True), (80, 299, False),
                                    (80, 300, True), (90, 899, False), (90, 900, True)):
        assert sp.decide(inputs(pct=pct, elapsed=elapsed)).block is expected


def test_unknown_usage_or_clock_never_withholds():
    for pct, elapsed in ((None, 1), (float("nan"), 1), (85, None), (85, -1)):
        assert sp.decide(inputs(pct=pct, elapsed=elapsed)).block


def test_urgent_event_bypasses_budget():
    inp = inputs()
    from dataclasses import replace
    inp.pending[0] = replace(inp.pending[0], rose=True)
    assert sp.decide(inp).by == sp.BY_URGENT


def test_worker_never_uses_admin_budget():
    inp = inputs()
    inp.role = "worker"
    assert sp.decide(inp).by == sp.BY_RULE_ZERO


def test_strict_config_and_default_off():
    import pytest
    from shantytown.admin_wake_budget import parse
    assert parse({}).mode == "off"
    for value in ({"mode": "enforce"}, {"mode": "enforced"}, {"agent": ["a"]},
                  {"mode": "advise", "agents": [1]}):
        with pytest.raises(ValueError):
            parse(value)


def test_counter_records_urgent_and_advice_without_message_content(tmp_path):
    import json
    from shantytown.admin_wake_budget import record
    inp = inputs(mode="advise")
    record(tmp_path, inp, sp.decide(inp), now=1000)
    data = json.loads((tmp_path / "admin-wake-budget/admin.json").read_text())
    assert data["counts"] == {"would-hold": 1}
    assert data["operator_bypasses"] is None
    assert "worker" not in json.dumps(data)
    from dataclasses import replace
    inp.pending[0] = replace(inp.pending[0], rose=True)
    record(tmp_path, inp, sp.decide(inp), now=1001)
    data = json.loads((tmp_path / "admin-wake-budget/admin.json").read_text())
    assert data["counts"]["urgent-bypass"] == 1


def test_external_prompt_is_counted_only_when_explicitly_enabled(tmp_path):
    import json
    from shantytown.admin_wake_budget import prompt
    from shantytown.runtime import admin_budget_prompt_hooks
    (tmp_path / "crew").mkdir()
    (tmp_path / "crew/admin.json").write_text(json.dumps({"role": "administrator"}))
    assert admin_budget_prompt_hooks("administrator", tmp_path) == []
    prompt(tmp_path, "admin")
    assert not (tmp_path / "admin-wake-budget").exists()
    (tmp_path / "shantytown.toml").write_text(
        '[admin_wake_budget]\nmode="advise"\nagents=["admin"]\n')
    hooks = admin_budget_prompt_hooks("administrator", tmp_path)
    assert "shantytown.admin_wake_budget" in hooks[0]["hooks"][0]["command"]
    assert admin_budget_prompt_hooks("worker", tmp_path) == []
    prompt(tmp_path, "admin")
    prompt(tmp_path, "admin")
    data = json.loads((tmp_path / "admin-wake-budget/admin.external.json").read_text())
    assert data["external_prompt_bypasses"] == 2
    assert data["operator_identity"] == "UNKNOWN"


def test_gather_default_off_makes_no_extra_governor_read(tmp_path, monkeypatch):
    from shantytown import config
    from types import SimpleNamespace
    from shantytown.answer import Answer
    class Registry:
        def get(self, name):
            return SimpleNamespace(name=name, role="administrator")
    class Events:
        def pending(self, name):
            return []
    monkeypatch.setattr(sp.feed_mod, "gate_inputs", lambda *a: ([], 0, []))
    monkeypatch.setattr(sp.feed_mod, "haul_governor_verdict", lambda *a: (_ for _ in ()).throw(AssertionError("extra read")))
    # Busy-event liveness is irrelevant with no pending events.
    inp = sp.gather(tmp_path, "admin", reg=Registry(), events=Events(), now=1000)
    assert inp.admin_wake_mode == "off"


def test_config_roundtrip_and_unknown_keys(tmp_path):
    import pytest
    from shantytown import config
    path = tmp_path / "shantytown.toml"
    path.write_text('[admin_wake_budget]\nmode="advise"\nagents=["admin"]\n')
    assert config.load(tmp_path).admin_wake_budget.mode == "advise"
    path.write_text('[admin_wake_budget]\nmode="advise"\nagent=["admin"]\n')
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)


def test_enabled_gather_reads_selected_claude_lane_without_persisting(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    (tmp_path / "shantytown.toml").write_text(
        '[admin_wake_budget]\nmode="advise"\nagents=["admin"]\n')
    card = SimpleNamespace(name="admin", role="administrator", harness="claude")
    class Registry:
        def get(self, name):
            return card
    class Events:
        def pending(self, name):
            return []
    class Clock:
        def last(self, name):
            return 950
    calls = []
    def verdict(root, selected):
        calls.append(selected)
        return SimpleNamespace(signal_lost=False, by_window={"seven_day": 90})
    monkeypatch.setattr(sp.feed_mod, "gate_inputs", lambda *a: ([], 0, []))
    monkeypatch.setattr(sp.feed_mod, "haul_governor_verdict", verdict)
    inp = sp.gather(tmp_path, "admin", reg=Registry(), events=Events(), wake_log=Clock(), now=1000)
    assert calls == [card]
    assert (inp.admin_usage_pct, inp.admin_wake_elapsed) == (90, 50)
    # A selected Codex account cannot borrow the Claude account's cadence.
    card.harness = "codex"
    inp = sp.gather(tmp_path, "admin", reg=Registry(), events=Events(), wake_log=Clock(), now=1000)
    assert inp.admin_wake_mode == "off"
    assert calls == [card]
