"""A failed MCP containment preparation is CANNOT_TELL, never a crash.

aegis-5x2x c10: `st agent spawn --ephemeral` died with "NameError: name
'subprocess' is not defined". The except clause around mcp_limits.prepare_launch
names subprocess.SubprocessError, and Python evaluates that name only when the
body raises, so the happy path never noticed the missing import. The crash
happened after the pane existed, leaving a LAUNCHING job at a bare shell."""
from types import SimpleNamespace

import pytest

from shantytown import cli, job_launch, mcp_limits
from shantytown.protocols import Agent


@pytest.mark.parametrize("error", [RuntimeError("parent not ready"), OSError("gone")])
def test_failed_preparation_is_reported_not_raised(tmp_path, monkeypatch, capsys, error):
    def fail(*_a, **_kw):
        raise error
    monkeypatch.setattr(cli, "_administrator_launch", lambda *a: False)
    monkeypatch.setattr(cli.quiet_time_mod, "read", lambda *a: SimpleNamespace(held=False))
    monkeypatch.setattr(job_launch, "for_card", lambda *a: None)
    monkeypatch.setattr(cli, "_window_launch_gate", lambda *a: None)
    monkeypatch.setattr(cli, "_account_launch_refusal", lambda *a, **kw: "")
    monkeypatch.setattr(cli.harness_mod, "require_role_harness", lambda *a, **kw: None)
    monkeypatch.setattr(cli.harness_mod, "name_for", lambda *a, **kw: "claude")
    monkeypatch.setattr(cli, "_session_for", lambda *a: "fixture-session")
    monkeypatch.setattr(mcp_limits, "prepare_launch", fail)
    started = []
    runtime = SimpleNamespace(compose=lambda *a: "fixture command never executed",
                              start=lambda *a: started.append(a))
    panes = SimpleNamespace(new_session=lambda *a, **kw: None, respawn=lambda *a, **kw: None)
    card = Agent("worker-1", role="worker", harness="claude")
    assert cli._launch_admitted(SimpleNamespace(root=tmp_path), card, panes, runtime) == cli.CANNOT_TELL
    assert started == []
    assert "MCP containment preparation failed" in capsys.readouterr().err
