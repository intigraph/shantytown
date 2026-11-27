"""aegis-8et F1: a refused launch records WHY, so the job ledger can name the cause.

Since #747 a job that is not delivered ends as `launch refused (<why>)`, where <why>
is `a._startup_failure`. Most `return REFUSED` paths in `_launch_admitted` printed to
stderr and never set it, so 13 of 24 delivery failures in the census carried only the
generic "see the spawner's stderr" and the trust-surface subcause could not be counted.

One test per path class: the refusal is returned, stderr still carries the line, and
the ledger copy names the cause (one line, bounded). A structural guard fails when any
`return REFUSED` in `_launch_admitted` skips the recording helper, and a synthetic
inverse proves the guard bites.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from types import SimpleNamespace

import pytest

from shantytown import cli
from shantytown import ephemeral as eph
from shantytown import job_launch
from shantytown import provision as prov_mod
from shantytown.provision import ProvisionError
from shantytown.workspace import WorkspaceError

GENERIC = "see the spawner's stderr"


class Panes:
    def __init__(self, fail: str = ""):
        self.fail = fail

    def new_session(self, session, cwd=None):
        if self.fail:
            raise RuntimeError(self.fail)

    respawn = new_session


class Runtime:
    def __init__(self, compose_error: Exception | None = None):
        self.compose_error = compose_error

    def compose(self, card):
        if self.compose_error:
            raise self.compose_error
        return "claude"

    def settings_path(self, card):
        return None


@pytest.fixture
def launch(tmp_path, monkeypatch):
    """_launch_admitted with every seam passing; a test breaks exactly one."""
    args = SimpleNamespace(root=str(tmp_path))
    card = SimpleNamespace(name="eph-task-abc123", workspace=str(tmp_path / "ws"))
    monkeypatch.setattr(cli, "_administrator_launch", lambda a, c: False)
    monkeypatch.setattr(cli.quiet_time_mod, "read", lambda root: SimpleNamespace(held=False))
    monkeypatch.setattr(job_launch, "for_card", lambda root, c: None)
    monkeypatch.setattr(cli.window_mod, "active", lambda root: None)
    monkeypatch.setattr(cli, "_account_launch_refusal", lambda a, c, **k: "")
    monkeypatch.setattr(cli.harness_mod, "name_for", lambda c, root=None: "claude")
    monkeypatch.setattr(cli.harness_mod, "require_role_harness", lambda c, root=None: None)
    monkeypatch.setattr(cli, "_session_for", lambda c: "sess")
    monkeypatch.setattr(cli, "ensure_workspace", lambda c: None)
    monkeypatch.setattr(cli, "_refresh_clone", lambda path: None)
    monkeypatch.setattr(cli, "provision_ws", lambda *a, **k: ["bobbin"])
    monkeypatch.setattr(eph, "reapply_attended_settings", lambda root, name: None)
    monkeypatch.setattr(eph, "read", lambda root, name: {"job": "task"})
    monkeypatch.setattr(prov_mod, "skills_linked", lambda ws: [])

    def run(panes=None, runtime=None):
        return cli._launch_admitted(args, card, panes or Panes(), runtime or Runtime())

    run.args = args
    return run


def _refused(launch, capsys, *, stderr_has: str, ledger_has: str):
    assert launch() == cli.REFUSED
    assert "  refused: " + stderr_has in capsys.readouterr().err   # stderr line unchanged
    why = launch.args._startup_failure
    assert ledger_has in why
    assert GENERIC not in why and "\n" not in why and len(why) <= cli._LAUNCH_REFUSAL_LEDGER_MAX


# --- one test per path class -------------------------------------------------

def test_gaming_hold_records_its_reason(launch, monkeypatch, capsys):
    status = SimpleNamespace(held=True, refusal="gaming hold: launches paused",
                             reasons=["gaming"], state="held",
                             override_lines=lambda inv: [])
    monkeypatch.setattr(cli.quiet_time_mod, "read", lambda root: status)
    monkeypatch.setattr(cli, "_despite_hold", lambda a: False)
    _refused(launch, capsys, stderr_has="gaming hold: launches paused",
             ledger_has="gaming hold: launches paused")


def test_unavailable_launch_binding_records_its_reason(launch, monkeypatch, capsys):
    def boom(root, card):
        raise OSError("no binding file")
    monkeypatch.setattr(job_launch, "for_card", boom)
    _refused(launch, capsys, stderr_has="protected job launch binding unavailable",
             ledger_has="protected job launch binding unavailable")


def test_maintenance_window_records_its_reason(launch, monkeypatch, capsys):
    monkeypatch.setattr(cli.window_mod, "active",
                        lambda root: {"id": "w-1", "state": "draining"})
    _refused(launch, capsys, stderr_has="maintenance window 'w-1' is draining",
             ledger_has="maintenance window 'w-1' is draining")


def test_account_admission_refusal_records_its_reason(launch, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_account_launch_refusal",
                        lambda a, c, **k: "account primary is at its cap 3/2")
    _refused(launch, capsys, stderr_has="account primary is at its cap 3/2",
             ledger_has="account primary is at its cap 3/2")


def test_compose_refusal_records_its_reason(launch, capsys):
    runtime = Runtime(ValueError("harness 'x' has no capability y"))
    assert launch(runtime=runtime) == cli.REFUSED
    assert "harness 'x' has no capability y" in launch.args._startup_failure
    assert GENERIC not in launch.args._startup_failure
    assert "  refused: harness 'x' has no capability y" in capsys.readouterr().err


def test_workspace_refusal_records_its_reason(launch, monkeypatch, capsys):
    def boom(card):
        raise WorkspaceError("shared checkout missing for repo r")
    monkeypatch.setattr(cli, "ensure_workspace", boom)
    _refused(launch, capsys, stderr_has="shared checkout missing for repo r",
             ledger_has="shared checkout missing for repo r")


def test_foreign_trust_surface_refusal_records_its_reason(launch, monkeypatch, capsys):
    """The subcause the census could not count: a provisioning refusal (foreign
    .mcp.json, settings st did not write) now arrives in the ledger verbatim."""
    def boom(*a, **k):
        raise eph.Refused("foreign .mcp.json: bytes do not match what provisioning wrote")
    monkeypatch.setattr(cli, "provision_ws", boom)
    _refused(launch, capsys, stderr_has="foreign .mcp.json: bytes do not match",
             ledger_has="foreign .mcp.json: bytes do not match")


def test_provision_error_records_its_reason(launch, monkeypatch, capsys):
    def boom(*a, **k):
        raise ProvisionError("template render failed: bobbin")
    monkeypatch.setattr(cli, "provision_ws", boom)
    _refused(launch, capsys, stderr_has="template render failed: bobbin",
             ledger_has="template render failed: bobbin")


def test_task_job_with_no_mcp_servers_records_its_reason(launch, monkeypatch, capsys):
    monkeypatch.setattr(cli, "provision_ws", lambda *a, **k: [])
    _refused(launch, capsys, stderr_has="eph-task-abc123: task job resolved NO MCP servers",
             ledger_has="task job resolved NO MCP servers")


def test_session_start_refusal_records_its_reason(launch, capsys):
    assert launch(panes=Panes("session sess already exists")) == cli.REFUSED
    assert "session sess already exists" in launch.args._startup_failure
    assert "  refused: session sess already exists" in capsys.readouterr().err


def test_recorded_reason_is_one_bounded_line(launch, monkeypatch):
    monkeypatch.setattr(cli, "_account_launch_refusal",
                        lambda a, c, **k: "first line\n" + "x" * 1000 + "\nlast")
    assert launch() == cli.REFUSED
    why = launch.args._startup_failure
    assert "\n" not in why and len(why) == cli._LAUNCH_REFUSAL_LEDGER_MAX
    assert why.startswith("first line x")


def test_spawn_ledger_line_names_the_recorded_cause(launch):
    """The spawner writes `launch refused ({why})` from a._startup_failure; the
    generic text appears only when nothing was recorded."""
    assert launch(panes=Panes("session sess already exists")) == cli.REFUSED
    why = getattr(launch.args, "_startup_failure", "") or GENERIC
    assert f"launch refused ({why})" == "launch refused (session sess already exists)"


# --- the guard, and its inverse ---------------------------------------------

def bare_refusals(source: str) -> list[int]:
    """Line numbers of `return REFUSED` that skip the recording helper."""
    tree = ast.parse(textwrap.dedent(source))
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Return) and isinstance(n.value, ast.Name)
            and n.value.id == "REFUSED"]


def test_no_refusal_in_launch_admitted_skips_the_recorder():
    assert bare_refusals(inspect.getsource(cli._launch_admitted)) == []


def test_helpers_that_return_refusals_record_them():
    for fn in (cli._refuse_gaming, cli._window_launch_gate):
        src = inspect.getsource(fn)
        assert "_startup_failure" in src or "_launch_refused(" in src, fn.__name__


def test_guard_fails_on_a_refusal_without_a_recorded_reason():
    """Inverse: today's shape (print, then bare return) is flagged."""
    old = '''
    def f(a):
        try:
            g()
        except OSError as e:
            print(f"  refused: {e}", file=sys.stderr)
            return REFUSED
    '''
    assert bare_refusals(old) == [7]
    new = old.replace('print(f"  refused: {e}", file=sys.stderr)\n            return REFUSED',
                      'return _launch_refused(a, e)')
    assert bare_refusals(new) == []
