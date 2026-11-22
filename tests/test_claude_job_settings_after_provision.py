"""Launch provisioning rewrote a Claude job's settings.local.json, so the trust
guard refused the folder-trust dialog and the job never started; it also lost
the per-PR allowlist (aegis-e579 finding 3, eph-review-2e5bdf on camayoc#268).
st now puts the job's exact allowlist back after provisioning and records the
new hash for the guard."""
import hashlib
import json
import os
import subprocess
import time

import pytest

from shantytown import ephemeral as eph

KIT = ["homelab", "bobbin"]
PROVISIONED = {"permissions": {"deny": ["AskUserQuestion"], "allow": ["Bash(*)"]},
               "enabledMcpjsonServers": KIT,
               "hooks": {"PreCompact": [{"hooks": [{"type": "command", "command": "st-precompact"}]}]}}


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def job(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    ws = tmp_path / "ws"
    git(tmp_path, "init", "-q", str(ws))
    git(ws, "config", "user.email", "t@t"); git(ws, "config", "user.name", "t")
    (ws / "README").write_text("x\n")
    git(ws, "add", "-A"); git(ws, "commit", "-qm", "main")
    rec = dict(name="eph-review-a1b2c3", job="review", repo="intigraph/example", pr=268,
               harness="claude", workspace=str(ws), item="aegis-x", administrator="sattler",
               deadline=time.time() + 600, state="live",
               worktree_base_sha=git(ws, "rev-parse", "HEAD"))
    written = eph.write_attended_settings(rec, unattended=False)
    rec["kit_settings_sha256"] = eph.kit_settings_sha256(written)
    eph.write(root, rec)
    return root, ws, rec


def provision(ws):
    (ws / ".claude" / "settings.local.json").write_text(json.dumps(PROVISIONED, indent=2))


def test_provisioning_overwrite_used_to_refuse_the_trust_dialog(job):
    root, ws, rec = job
    provision(ws)
    assert "differs from the settings st wrote" in eph.trust_surface_refusal(
        eph.read(root, rec["name"]), expected_servers=KIT)


def test_reapply_keeps_provisioning_and_restores_the_exact_allowlist(job):
    root, ws, rec = job
    provision(ws)
    path = eph.reapply_attended_settings(root, rec["name"])
    cfg = json.loads(path.read_text())
    want = eph.attended_settings(rec, unattended=False)["permissions"]
    assert cfg["permissions"]["allow"] == want["allow"]          # provisioning's Bash(*) is gone
    assert "Bash(*)" not in cfg["permissions"]["allow"]
    assert set(cfg["permissions"]["deny"]) == set(want["deny"]) | {"AskUserQuestion"}
    assert cfg["enabledMcpjsonServers"] == KIT and cfg["hooks"] == PROVISIONED["hooks"]
    new = eph.read(root, rec["name"])
    assert new["kit_settings_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert eph.trust_surface_refusal(new, expected_servers=KIT) == ""


def test_a_later_edit_is_still_refused(job):
    root, ws, rec = job
    provision(ws)
    path = eph.reapply_attended_settings(root, rec["name"])
    path.write_text(path.read_text().replace("Read(./**)", "Bash(*)"))
    assert "differs from the settings st wrote" in eph.trust_surface_refusal(
        eph.read(root, rec["name"]), expected_servers=KIT)


def test_jobs_without_st_settings_are_left_alone(job):
    root, ws, rec = job
    eph.write(root, dict(rec, kit_settings_sha256=None))
    provision(ws)
    before = (ws / ".claude" / "settings.local.json").read_text()
    assert eph.reapply_attended_settings(root, rec["name"]) is None
    assert (ws / ".claude" / "settings.local.json").read_text() == before
    eph.write(root, dict(rec, harness="codex"))
    assert eph.reapply_attended_settings(root, rec["name"]) is None


def test_never_writes_through_a_symlink(job, tmp_path):
    root, ws, rec = job
    target = tmp_path / "elsewhere.json"
    target.write_text("{}")
    local = ws / ".claude" / "settings.local.json"
    local.unlink()
    os.symlink(target, local)
    with pytest.raises(eph.Refused):
        eph.reapply_attended_settings(root, rec["name"])
    assert target.read_text() == "{}"


@pytest.mark.parametrize("with_kit", [True, False])
def test_task_provisioning_records_only_the_bytes_it_emitted(job, with_kit):
    from shantytown import provision as provisioning
    from shantytown.protocols import Agent

    root, ws, rec = job
    rec.update(job="task", kit_settings_sha256=None)
    eph.write(root, rec)
    templates = root / "provision"
    if with_kit:
        templates.mkdir()
        (templates / provisioning.MCP_TEMPLATE).write_text(json.dumps({"mcpServers": {}}))
        (templates / "settings.local.json").write_text(json.dumps(PROVISIONED))
    card = Agent(name=rec["name"], role="worker", harness="claude", workspace=str(ws))
    provisioning.provision(card, root)
    emitted = (ws / ".claude" / "settings.local.json").read_bytes()
    current = eph.read(root, rec["name"])
    assert current["kit_settings_sha256"] == hashlib.sha256(emitted).hexdigest()
    assert eph.trust_surface_refusal(current, expected_servers=KIT) == ""
    # Recording an emitted task file must not weaken the later trust check.
    (ws / ".claude" / "settings.local.json").write_bytes(emitted + b" ")
    assert "differs from the settings st wrote" in eph.trust_surface_refusal(
        current, expected_servers=KIT)


def test_task_consent_cannot_attest_another_workspace_or_changed_bytes(job, tmp_path):
    from shantytown import provision as provisioning
    from shantytown.protocols import Agent

    root, ws, rec = job
    rec.update(job="task", kit_settings_sha256=None)
    eph.write(root, rec)
    provision(ws)
    card = Agent(name=rec["name"], role="worker", harness="claude", workspace=str(ws))
    with pytest.raises(provisioning.ProvisionError, match="bytes just provisioned"):
        provisioning._record_task_consent(card, root, ws, "{}")
    with pytest.raises(provisioning.ProvisionError, match="launching job"):
        provisioning._record_task_consent(card, root, tmp_path / "other", "{}")
    assert eph.read(root, rec["name"])["kit_settings_sha256"] is None


@pytest.mark.parametrize("change", [{"state": eph.DONE}, {"harness": "codex"}])
def test_task_consent_rejects_completed_or_different_harness_jobs(job, change):
    from shantytown import provision as provisioning
    from shantytown.protocols import Agent

    root, ws, rec = job
    rec.update(job="task", kit_settings_sha256=None, **change)
    eph.write(root, rec)
    provision(ws)
    card = Agent(name=rec["name"], role="worker", harness="claude", workspace=str(ws))
    with pytest.raises(provisioning.ProvisionError, match="launching job"):
        provisioning._record_task_consent(
            card, root, ws, (ws / ".claude" / "settings.local.json").read_text())
    assert eph.read(root, rec["name"])["kit_settings_sha256"] is None
