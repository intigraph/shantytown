"""aegis-za4f.20: role settings that drift from the code are re-emitted, and a
live agent still on older settings is cycled at idle (administrator: notice).

The positive control that motivated this: #764's operator-capture hook was in
the installed st, but administrator.settings.json predated it and the live pane
had launched on it, so nothing was captured.
"""
import json
from types import SimpleNamespace

import pytest

from shantytown import cli, cycle, settings_drift
from shantytown.launched import CURRENT, STALE, FilesLaunches

NEW_HOOK = "echo st-new-hook-za4f20"


def _store(tmp_path):
    crew = tmp_path / "crew"
    crew.mkdir()
    for name, role in (("sattler", "administrator"), ("dearing", "worker")):
        (crew / f"{name}.json").write_text(json.dumps(
            {"role": role, "pane": f"st-{name}"}))
    return tmp_path


class _Panes:
    def __init__(self, live):
        self.live = set(live)

    def exists(self, pane):
        return pane in self.live


def _cards(root):
    return cli._registry(SimpleNamespace(root=root, backend=None)).all().exact()


def _add_hook_to_builder(monkeypatch):
    real = cli.settings_for_role

    def builder(role, root=None, harness_name=None):
        out = real(role, root=root, harness_name=harness_name)
        out["hooks"]["UserPromptSubmit"] = list(out["hooks"]["UserPromptSubmit"]) + [
            {"hooks": [{"type": "command", "command": NEW_HOOK}]}]
        return out
    monkeypatch.setattr(cli, "settings_for_role", builder)


def _sweep(monkeypatch, root, live=("st-sattler", "st-dearing")):
    a = SimpleNamespace(root=root, dry_run=False, backend=None)
    monkeypatch.setattr(cli, "_runtime_checkpoint",
                        lambda a, card, ev, headline=None: dict(text=headline, item="", nodes=[]))
    monkeypatch.setattr(cli.notify_mod, "auto_cycle_enabled", lambda: True)
    logs = []
    asked = cli._settings_drift_sweep(a, _cards(root), _Panes(live), logs.append)
    return asked, logs


def _launch_everyone(root):
    launches = FilesLaunches(root / "launched")
    for name, role in (("sattler", "administrator"), ("dearing", "worker")):
        launches.record(name, root / "settings" / f"{role}.settings.json")
    return launches


@pytest.fixture
def root(tmp_path):
    r = _store(tmp_path)
    cli._emit_role_settings(r, {"administrator", "worker"})
    return r


def test_unchanged_settings_rewrite_nothing_and_cycle_nobody(root, monkeypatch):
    launches = _launch_everyone(root)
    path = root / "settings" / "worker.settings.json"
    before = path.read_bytes()
    asked, logs = _sweep(monkeypatch, root)
    assert asked == [] and path.read_bytes() == before
    assert launches.verdict("dearing") == CURRENT
    assert cycle.Requests(root).pending() == {}
    assert settings_drift.admin_notices(_cards(root), launches) == []


def test_a_new_builder_hook_is_re_emitted_flagged_and_cycled_at_idle(root, monkeypatch):
    launches = _launch_everyone(root)
    _add_hook_to_builder(monkeypatch)
    asked, logs = _sweep(monkeypatch, root)
    # (a) the file is re-emitted from the current code
    for role in ("administrator", "worker"):
        assert NEW_HOOK in (root / "settings" / f"{role}.settings.json").read_text()
    # (b) both live agents are now on older settings than their file
    assert launches.verdict("dearing") == STALE and launches.verdict("sattler") == STALE
    notices = settings_drift.admin_notices(_cards(root), launches)
    assert any(n.startswith("SETTINGS STALE: sattler") for n in notices)
    # (c) the worker gets an idle-only REPLACE cycle; the administrator does not
    assert asked == ["dearing"]
    req = cycle.Requests(root).pending()
    assert set(req) == {"dearing"}
    assert req["dearing"]["auto"] and req["dearing"]["no_in_place"]
    assert req["dearing"]["settings_stale"]
    # the relaunch stamps the re-emitted file, which carries the new hook
    launches.record("dearing", root / "settings" / "worker.settings.json")
    assert launches.verdict("dearing") == CURRENT
    assert NEW_HOOK in launches.snapshot("dearing").decode()


def test_a_down_agent_is_not_cycled(root, monkeypatch):
    _launch_everyone(root)
    _add_hook_to_builder(monkeypatch)
    asked, _ = _sweep(monkeypatch, root, live=())
    assert asked == [] and cycle.Requests(root).pending() == {}


def test_a_render_that_would_drop_a_hand_hook_is_held(root, monkeypatch):
    path = root / "settings" / "worker.settings.json"
    data = json.loads(path.read_text())
    data["hooks"]["UserPromptSubmit"].append(
        {"hooks": [{"type": "command", "command": "echo operator-added"}]})
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    _, logs = _sweep(monkeypatch, root)
    assert path.read_bytes() == before
    assert any("held" in line and str(path) in line for line in logs)


def test_the_depth_sweep_does_not_withdraw_a_settings_request(root):
    from test_auto_cycle import _world, _sweep
    from test_cycle import _saturated_pane

    ac, panes, reqs, *_ = _world(root, _saturated_pane(646.0))
    _sweep(ac)  # creates the depth episode that a below-threshold sweep clears
    reqs.request("kelly", "cp", auto=True, no_in_place=True, settings_stale=True)
    panes.screens["p-kelly"] = _saturated_pane(40.0)
    _sweep(ac)
    assert reqs.pending()["kelly"]["settings_stale"] is True


def test_stale_worker_notice_does_not_promise_an_automatic_cycle(root):
    launches = _launch_everyone(root)
    path = root / "settings" / "worker.settings.json"
    path.write_text(path.read_text() + " ")
    notice = next(n for n in settings_drift.admin_notices(_cards(root), launches)
                  if "dearing" in n)
    assert "replacement cycle" in notice
    assert "tend cycles" not in notice


def _declared(monkeypatch, tmp_path, operators):
    from shantytown import actor_identity, deployment, operator_capture as oc
    from tests.test_operator_capture import _cli_store
    root = _cli_store(tmp_path)
    (root / "shantytown.toml").write_text(f"[inbox]\noperators = {json.dumps(operators)}\n")
    monkeypatch.delenv(oc.OPERATOR_KEY, raising=False)
    monkeypatch.setattr(deployment, "read_pointer", lambda: None)
    # The operator's own channel: a protected-UID identity, not an env claim.
    monkeypatch.setattr(actor_identity, "authenticated_actor", lambda: "stiwi")
    return root


def test_inbox_capture_defaults_to_the_declared_operators(tmp_path, monkeypatch):
    from shantytown import operator_capture as oc
    from tests.test_operator_capture import _inbox
    root = _declared(monkeypatch, tmp_path, ["stiwi"])
    _inbox(monkeypatch, root, operator=None)
    found = oc.records(root)
    assert [(r.text, r.source_kind) for r in found] == [("ship it", oc.SOURCE_KIND)]


def test_inbox_capture_still_needs_a_named_operator(tmp_path, monkeypatch):
    from shantytown import operator_capture as oc
    from tests.test_operator_capture import _inbox
    root = _declared(monkeypatch, tmp_path, [])
    _inbox(monkeypatch, root, operator=None)
    assert not oc.spool_dir(root).exists() or oc.records(root) == []
