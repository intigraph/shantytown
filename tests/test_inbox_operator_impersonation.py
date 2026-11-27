"""aegis-vpy: a job or crew process can never sign a message as the operator,
and a scratch-root send can never reach the live deployment.

Measured 2026-11-27: an ephemeral job testing `st inbox` against a scratch root,
with SHANTY_AGENT=stiwi in its environment, delivered a DURABLE "[from stiwi]"
message to a lead, who acted on it as operator direction.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from shantytown import actor_identity as identity
from shantytown import cli
from shantytown import ephemeral as eph

OPERATOR = "synthetic-operator"
JOB = "eph-task-abc123"


@pytest.fixture
def unmigrated(monkeypatch):
    """The measured host: no protected identity policy, no tmux pane."""
    monkeypatch.setattr(identity, "authenticated_actor", lambda: None)
    monkeypatch.delenv("TMUX_PANE", raising=False)


def _point_at(root: Path) -> None:
    pointer = Path(os.environ["XDG_CONFIG_HOME"]) / "shantytown" / "root"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(f"{root}\n")


def _deployment(tmp_path: Path, operators=(OPERATOR,)) -> Path:
    root = tmp_path / "deploy" / ".shanty"
    root.mkdir(parents=True)
    names = ", ".join(f'"{n}"' for n in operators)
    (root / "shantytown.toml").write_text(f"[inbox]\noperators = [{names}]\n")
    return root


def _inside(monkeypatch, job: str | None):
    monkeypatch.setattr(eph, "live", lambda root: [{"name": job}] if job else [])
    monkeypatch.setattr(eph, "inside_ephemeral", lambda root, **_: job)
    monkeypatch.setattr(eph, "ancestor_pids", lambda: [os.getpid()])
    monkeypatch.setattr(cli, "_panes", lambda a: SimpleNamespace())


def test_job_claiming_the_operator_is_refused(unmigrated, monkeypatch, tmp_path):
    root = _deployment(tmp_path)
    _point_at(root)
    _inside(monkeypatch, JOB)
    monkeypatch.setenv("SHANTY_AGENT", OPERATOR)
    assert cli._verified_sender(SimpleNamespace(root=root, me=None), None) == (None, False)


def test_job_claiming_a_crew_name_is_refused(unmigrated, monkeypatch, tmp_path):
    root = _deployment(tmp_path)
    _point_at(root)
    _inside(monkeypatch, JOB)
    monkeypatch.setenv("SHANTY_AGENT", "synthetic-lead")
    assert cli._verified_sender(SimpleNamespace(root=root, me=None), None) == (None, False)


def test_job_that_unset_its_name_is_still_attributed_as_the_job(unmigrated, monkeypatch, tmp_path):
    root = _deployment(tmp_path)
    _point_at(root)
    _inside(monkeypatch, JOB)
    monkeypatch.delenv("SHANTY_AGENT", raising=False)
    assert cli._verified_sender(SimpleNamespace(root=root, me=None), None) == (JOB, True)


def test_job_detected_on_the_deployment_even_from_a_scratch_root(unmigrated, monkeypatch, tmp_path):
    """The scratch root's own ledger is empty; the deployment's is not."""
    root = _deployment(tmp_path)
    _point_at(root)
    seen = []
    monkeypatch.setattr(eph, "live", lambda r: seen.append(Path(r)) or
                        ([{"name": JOB}] if Path(r) == root else []))
    monkeypatch.setattr(eph, "inside_ephemeral",
                        lambda r, **_: JOB if Path(r) == root else None)
    monkeypatch.setattr(eph, "ancestor_pids", lambda: [os.getpid()])
    monkeypatch.setattr(cli, "_panes", lambda a: SimpleNamespace())
    monkeypatch.setenv("SHANTY_AGENT", OPERATOR)
    a = SimpleNamespace(root=tmp_path / "scratch", me=None, dry_run=True)
    assert cli._enclosing_job(a) == JOB
    assert root in seen


def test_crew_process_claiming_the_operator_is_refused(unmigrated, monkeypatch, tmp_path):
    root = _deployment(tmp_path)
    _point_at(root)
    _inside(monkeypatch, None)
    monkeypatch.setenv("SHANTY_AGENT", OPERATOR)
    assert cli._verified_sender(SimpleNamespace(root=root, me=None), None) == (None, False)


def test_operator_list_of_the_deployment_applies_to_a_scratch_config(unmigrated, monkeypatch, tmp_path):
    """An empty operator list in a scratch root must not unlock the name."""
    root = _deployment(tmp_path)
    _point_at(root)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    assert OPERATOR in cli._operator_names(SimpleNamespace(root=scratch))


def test_ordinary_crew_sender_is_unchanged(unmigrated, monkeypatch, tmp_path):
    root = _deployment(tmp_path)
    _point_at(root)
    _inside(monkeypatch, None)
    monkeypatch.setenv("SHANTY_AGENT", "synthetic-crew")
    assert cli._verified_sender(SimpleNamespace(root=root, me=None), None) == ("synthetic-crew", True)


def test_verified_operator_principal_may_sign(monkeypatch, tmp_path):
    """The operator's OWN protected-UID identity is their channel, not an env claim."""
    root = _deployment(tmp_path)
    _point_at(root)
    _inside(monkeypatch, None)
    monkeypatch.setattr(identity, "authenticated_actor", lambda: OPERATOR)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.delenv("SHANTY_AGENT", raising=False)
    assert cli._verified_sender(SimpleNamespace(root=root, me=None), None) == (OPERATOR, True)


def test_scratch_root_send_is_refused_on_a_deployed_box(unmigrated, monkeypatch, tmp_path):
    root = _deployment(tmp_path)
    _point_at(root)
    _inside(monkeypatch, None)
    monkeypatch.setenv("SHANTY_AGENT", "synthetic-crew")
    scratch = SimpleNamespace(root=tmp_path / "scratch", me=None, dry_run=False)
    assert cli._verified_sender(scratch, None) == (None, False)
    preview = SimpleNamespace(root=tmp_path / "scratch", me=None, dry_run=True)
    assert cli._verified_sender(preview, None) == ("synthetic-crew", True)


def test_scratch_root_inbox_command_writes_nothing(unmigrated, monkeypatch, tmp_path):
    """End to end through `st inbox -d`: refused before any store is touched."""
    root = _deployment(tmp_path)
    _point_at(root)
    _inside(monkeypatch, None)
    scratch = tmp_path / "scratch" / ".shanty"
    (scratch / "crew").mkdir(parents=True)
    monkeypatch.setenv("SHANTY_AGENT", OPERATOR)
    monkeypatch.setattr(cli, "_message_recipient",
                        lambda a: pytest.fail("a refused send must not look up a recipient"))
    code = cli.main(["--registry", "files", "--backend", "files", "--root", str(scratch),
                     "inbox", "-d", "synthetic-lead", "do", "the", "thing"])
    assert code == cli.REFUSED
    assert not (scratch / "inbox").exists() or not any((scratch / "inbox").rglob("*"))


def test_config_rejects_a_malformed_operator_list(tmp_path):
    from shantytown.config import ConfigError, load
    (tmp_path / "shantytown.toml").write_text('[inbox]\noperators = "stiwi"\n')
    with pytest.raises(ConfigError, match="inbox.operators"):
        load(tmp_path)
