"""A real observed cold launch can resurface work; a synthetic start cannot."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from shantytown import cli, deferrals, resume_launch as launch
from shantytown.protocols import Agent

NOW = datetime(2026, 11, 5, 22, tzinfo=timezone.utc)
ARG = "operator@2026-11-05T21:00:00Z"


def record(root, **change):
    options = dict(administrator=True, harness="codex", session="fixture-session",
                   cold=True, ordinary=True, live=True, hooks=True, inbox=True, now=NOW)
    options.update(change)
    return launch.record(root, Agent("operator"), **options)


def test_native_receipt_is_root_agent_time_and_host_bound(tmp_path):
    assert launch.evaluate(ARG, tmp_path, NOW)[0] is False
    assert record(tmp_path)
    assert launch.evaluate(ARG, tmp_path, NOW)[0] is True
    assert launch.evaluate("operator@2026-11-05T22:00:01Z", tmp_path, NOW)[0] is None
    assert launch.evaluate("other@2026-11-05T21:00:00Z", tmp_path, NOW)[0] is False
    assert launch.evaluate(ARG, tmp_path / "other-root", NOW)[0] is False
    assert launch.evaluate(ARG, tmp_path, NOW - timedelta(hours=1))[0] is None
    assert launch.evaluate(ARG, None, NOW)[0] is None
    # An event is historical evidence, not an indefinitely cached live status.
    assert launch.evaluate(ARG, tmp_path, NOW + timedelta(days=2))[0] is True


@pytest.mark.parametrize("field,value", [
    ("administrator", False), ("cold", False), ("ordinary", False),
    ("live", False), ("hooks", False), ("inbox", False), ("harness", "claude"),
    ("administrator", "true"),
])
def test_nonqualifying_observations_never_create_evidence(tmp_path, field, value):
    assert record(tmp_path, **{field: value}) is False
    assert not (tmp_path / "notify").exists()


@pytest.mark.parametrize("patch", [
    {"host": "other-host"}, {"root": "/other-root"}, {"agent": "other"},
    {"harness": "claude"}, {"administrator": False}, {"inbox": None},
    {"kind": "cycle"}, {"schema": True}, {"session": ""}, {"id": ""},
])
def test_wrong_or_malformed_receipts_are_unknown(tmp_path, patch):
    record(tmp_path)
    path = launch._path(tmp_path, "operator")
    data = json.loads(path.read_text()); data.update(patch); path.write_text(json.dumps(data))
    assert launch.evaluate(ARG, tmp_path, NOW)[0] is None


@pytest.mark.parametrize("fault", ["symlink", "directory-symlink", "writable", "oversize", "duplicate", "truncated"])
def test_untrusted_evidence_cannot_release(tmp_path, fault):
    record(tmp_path)
    path = launch._path(tmp_path, "operator")
    if fault == "symlink":
        other = path.with_name("copy"); path.rename(other); path.symlink_to(other)
    elif fault == "directory-symlink":
        other = path.parent.with_name("copy"); path.parent.rename(other); path.parent.symlink_to(other)
    elif fault == "writable":
        path.chmod(0o666)
    elif fault == "oversize":
        path.write_bytes(b" " * (launch.MAX_BYTES + 1))
    elif fault == "duplicate":
        path.write_text('{"schema":1,"schema":1}')
    else:
        path.write_text("{")
    assert launch.evaluate(ARG, tmp_path, NOW)[0] is None


def test_arbitrary_path_and_naive_time_are_not_conditions():
    for value in ("../operator@2026-11-05T21:00:00Z", "operator@now",
                  "operator@2026-11-05T21:00:00", "operator@2026-11-05Z",
                  "$(cmd)@2026-11-05T21:00:00Z"):
        with pytest.raises(ValueError):
            launch.validate(value)


def test_tend_can_read_cold_launch_without_starting_anything(tmp_path):
    record(tmp_path)
    row = dict(id="waiter", status="deferred", labels=["blocked:external"],
               notes="resume_when: cold-launch:" + ARG,
               defer_until=(NOW + timedelta(days=7)).isoformat())
    finding = deferrals.evaluate([row], NOW, root=tmp_path)[0]
    assert finding.met and deferrals.can_release(row, finding, NOW)


@pytest.mark.parametrize("mode,expected", [("ordinary", True), ("cycle", False),
    ("restore", False), ("override", False), ("dry-run", False),
    ("hooks-unknown", False), ("inbox-unacked", False), ("not-live", False)])
def test_actual_launcher_emits_only_after_qualifying_checks(tmp_path, monkeypatch, mode, expected):
    from shantytown import job_launch
    a = SimpleNamespace(root=tmp_path)
    card = Agent("operator", role="administrator", harness="codex")
    monkeypatch.setattr(cli, "_administrator_launch", lambda *a: True)
    monkeypatch.setattr(cli.quiet_time_mod, "read", lambda *a: SimpleNamespace(held=False))
    monkeypatch.setattr(job_launch, "for_card", lambda *a: ("private fixture",))
    monkeypatch.setattr(cli, "_window_launch_gate", lambda *a: None)
    monkeypatch.setattr(cli, "_account_launch_refusal", lambda *a, **kw: "")
    monkeypatch.setattr(cli, "_despite_hold", lambda *a: mode == "override")
    monkeypatch.setattr(cli.harness_mod, "require_role_harness", lambda *a, **kw: None)
    monkeypatch.setattr(cli.harness_mod, "name_for", lambda *a, **kw: "codex")
    monkeypatch.setattr(cli, "_session_for", lambda *a: "private-fixture-session")
    monkeypatch.setattr(cli, "_launched_now", lambda *a: None)
    monkeypatch.setattr(cli, "_record_launch_unretirement", lambda *a: True)
    monkeypatch.setattr(cli, "_observe_live", lambda *a: mode != "not-live")
    monkeypatch.setattr(cli, "_verify_live_hooks", lambda *a: cli.CANNOT_TELL if mode == "hooks-unknown" else cli.OK)
    monkeypatch.setattr(cli, "_deliver_startup_inbox", lambda *a: mode != "inbox-unacked")
    runtime = SimpleNamespace(compose=lambda *a: "fixture command never executed",
        start=lambda *a: None, settings_path=lambda *a: None, waiting_for_human=lambda *a: True)
    panes = SimpleNamespace(new_session=lambda *a, **kw: None, respawn=lambda *a, **kw: None,
                            capture=lambda *a: "consent")
    cli._launch_admitted(a, card, panes, runtime, dry_run=mode == "dry-run",
                        reuse_session=mode == "cycle", window_restore=mode == "restore")
    path = launch._path(tmp_path, card.name)
    assert path.exists() is expected
