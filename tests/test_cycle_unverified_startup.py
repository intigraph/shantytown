"""A delivery uncertainty cannot authorize killing a live replacement."""
from types import SimpleNamespace

import pytest

from shantytown import cli, cycle, provision
from shantytown.protocols import Agent


@pytest.mark.parametrize("observation", ["live", "unreadable", "dead"])
def test_respawn_uncertainty_preserves_live_replacement(tmp_path, monkeypatch, observation):
    card = Agent("worker", harness="claude")
    a = SimpleNamespace(root=tmp_path)
    effects = []
    monkeypatch.setattr(provision, "preflight_credentials", lambda *a: None)
    monkeypatch.setattr(cli, "_foreign_session_refusal", lambda *a: None)
    monkeypatch.setattr(cli, "_capture_history_before_kill", lambda *a: None)
    monkeypatch.setattr(cli, "_launch", lambda *a, **kw: effects.append(("launch", kw)) or cli.CANNOT_TELL)
    monkeypatch.setattr(cli, "_launch_admitted", lambda *a, **kw: effects.append(("fallback-admission", kw)) or cli.REFUSED)
    monkeypatch.setattr(cli, "_cmd_stop", lambda *a: pytest.fail("must not stop an unverified live replacement"))

    def capture(session):
        if observation == "unreadable":
            raise OSError("fixture capture unavailable")
        return observation

    panes = SimpleNamespace(capture=capture, exists=lambda *a: True)
    runtime = SimpleNamespace(is_live=lambda screen: screen == "live")
    result = cli._restart_cycle(a, card, "worker", "pane", panes, runtime,
                                cycle.Plan(cycle.RESPAWN, "fixture"), None)
    assert effects[0] == ("launch", {"reuse_session": True})
    if observation == "dead":
        assert result == (cli.REFUSED, cycle.RELAUNCH)
        assert len(effects) == 2 and effects[1][0] == "fallback-admission"
    else:
        assert result == (cli.CANNOT_TELL, cycle.RESPAWN)
        assert len(effects) == 1
