"""The card's permission opt-in must reach the DAEMON, not only the TUI
(aegis-7okaae).

Under Remote Control the model's shell commands execute in the app-server, and
`codex app-server` accepts NEITHER --dangerously-bypass-approvals-and-sandbox NOR
-s/--sandbox — only -c. So the client flag governed a process that was not the
one running the tools, and the daemon silently kept codex's default
`workspace-write`.

MEASURED 2026-09-11 with `codex sandbox`, from a crew workspace, both arms:

    workspace-write     touch <live br store>   -> Read-only file system
                        getent hosts github.com -> DNS-FAIL
    danger-full-access  touch <live br store>   -> WROTE-OK
                        getent hosts github.com -> DNS-OK

The live br store sits OUTSIDE every crew workspace, so `br close`,
`br comments add` and `st inbox -d` all failed from every codex session: three
dispatches in one day reported work done that could not be landed or closed.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from shantytown import harness as harness_mod

CODEX = harness_mod.get("codex")
from shantytown.protocols import Agent


def _launch(tmp_path, *, dangerous: bool) -> str:
    root = tmp_path / ".shanty"
    root.mkdir()
    (root / "shantytown.toml").write_text(
        '[env]\nSHANTY_REMOTE_CONTROL = "true"\n')
    cfg = root / "settings" / "codex" / "worker" / "config.toml"
    managed = cfg.parent / "packages" / "standalone" / "current" / "codex"
    managed.parent.mkdir(parents=True)
    managed.write_text("")
    return CODEX.launch(
        Agent(name="ellie", role="worker", workspace=str(tmp_path / "w"),
              dangerous=dangerous),
        str(cfg), root=root)


def test_a_dangerous_card_sets_the_policy_ON_THE_DAEMON(tmp_path):
    launch = _launch(tmp_path, dangerous=True)
    assert 'remote-control start -c sandbox_mode="danger-full-access"' in launch, (
        "the daemon start must carry the policy; the TUI flag cannot reach the "
        "process that actually runs the tools")
    assert '-c approval_policy="never"' in launch
    # the TUI flag is still there — this ADDS the daemon half, it does not move it
    assert "--dangerously-bypass-approvals-and-sandbox" in launch


def test_an_ORDINARY_card_leaves_the_sandbox_exactly_as_it_was(tmp_path):
    """THE CONTROL, and the reason this is opt-in.

    Without it, hardcoding the override would silently un-sandbox every codex
    worker on the fleet — the opposite of the per-card contract this repo keeps.
    """
    launch = _launch(tmp_path, dangerous=False)
    assert "sandbox_mode" not in launch
    assert "approval_policy" not in launch
    assert "--dangerously-bypass-approvals-and-sandbox" not in launch
    # and the daemon still starts, unchanged
    assert "codex remote-control start --json" in launch


def test_an_attended_TASK_JOB_daemon_gets_its_narrow_profile(tmp_path, monkeypatch, request):
    """aegis-za4f D1/D2. MEASURED 2026-11-25, codex-cli 0.161.0, `codex sandbox`:

        workspace-write                      -> DNS-FAIL, ledger RO, git dir RO
        + network_access + exact roots       -> DNS-OK, ledger OK, git dir OK;
                                                $HOME, st state, seeds config RO

    The spawner writes the profile into the job's own daemon home; the daemon
    start line must carry it, and still never danger-full-access.
    """
    from shantytown import ephemeral as eph
    from shantytown.codex_daemon import runtime_home
    import tempfile
    run = Path(tempfile.mkdtemp(prefix="st-", dir="/tmp"))  # socket path ceiling
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run))
    import shutil
    request.addfinalizer(lambda: shutil.rmtree(run, True))
    name = "eph-task-a1b2c3"
    rec = dict(job="task", harness="codex", name=name)
    eph.write_codex_job_sandbox(rec, runtime_home(name), unattended=False,
                                cache_home=tmp_path / "cache")
    root = tmp_path / ".shanty"
    root.mkdir()
    (root / "shantytown.toml").write_text('[env]\nSHANTY_REMOTE_CONTROL = "true"\n')
    cfg = root / "settings" / "codex" / "worker" / "config.toml"
    managed = cfg.parent / "packages" / "standalone" / "current" / "codex"
    managed.parent.mkdir(parents=True)
    managed.write_text("")
    launch = CODEX.launch(Agent(name=name, role="worker", workspace=str(tmp_path / "w")),
                          str(cfg), root=root)
    assert "remote-control start -c 'sandbox_mode=\"workspace-write\"'" in launch
    assert "sandbox_workspace_write.network_access=true" in launch
    assert "read-budget-v1" in launch
    assert "danger-full-access" not in launch and "approval_policy" not in launch
    # A crew card in the same runtime dir still reads nothing.
    (tmp_path / "crew").mkdir()
    assert "sandbox_workspace_write" not in _launch(tmp_path / "crew", dangerous=False)


def test_a_LOCAL_task_job_launch_carries_the_profile_on_the_tui(tmp_path, monkeypatch, request):
    """aegis-za4f. MEASURED 2026-11-25: eph-task-450024's settings home had no
    Remote Control package, so st fell back to LOCAL codex, where the tools run
    in the TUI process. The profile sat only on a daemon that never started, and
    `st work item show` failed StoreUnproven. The local launch must carry it."""
    import shutil, tempfile
    from shantytown import ephemeral as eph
    from shantytown.codex_daemon import runtime_home
    run = Path(tempfile.mkdtemp(prefix="st-", dir="/tmp"))
    request.addfinalizer(lambda: shutil.rmtree(run, True))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run))
    name = "eph-task-a1b2c3"
    eph.write_codex_job_sandbox(dict(job="task", harness="codex", name=name),
                                runtime_home(name), unattended=False,
                                cache_home=tmp_path / "cache")
    root = tmp_path / ".shanty"
    root.mkdir()
    (root / "shantytown.toml").write_text('[env]\nSHANTY_REMOTE_CONTROL = "true"\n')
    cfg = root / "settings" / "codex" / "worker" / "config.toml"
    cfg.parent.mkdir(parents=True)  # NO managed package: Remote Control falls back
    launch = CODEX.launch(Agent(name=name, role="worker", workspace=str(tmp_path / "w")),
                          str(cfg), root=root)
    assert "remote-control start" not in launch, "this arm must be the local fallback"
    assert "sandbox_workspace_write.network_access=true" in launch
    assert "read-budget-v1" in launch
    assert "danger-full-access" not in launch
    assert "--dangerously-bypass-approvals-and-sandbox" not in launch


def test_a_LOCAL_crew_launch_is_unchanged(tmp_path):
    root = tmp_path / ".shanty"
    root.mkdir()
    (root / "shantytown.toml").write_text('[env]\nSHANTY_REMOTE_CONTROL = "false"\n')
    cfg = root / "settings" / "codex" / "worker" / "config.toml"
    cfg.parent.mkdir(parents=True)
    launch = CODEX.launch(Agent(name="ellie", role="worker", workspace=str(tmp_path / "w")),
                          str(cfg), root=root)
    assert "sandbox_workspace_write" not in launch and "sandbox_mode" not in launch
