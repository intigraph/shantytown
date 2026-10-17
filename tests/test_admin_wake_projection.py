"""A scoped provision owns one budget hook, without rewriting role settings."""
import json

import pytest

from shantytown import provision as P
from shantytown.protocols import Agent
from shantytown.runtime import admin_budget_prompt_hooks


def configure(root, mode=None):
    path = root / "shantytown.toml"
    if mode is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(
            f'[admin_wake_budget]\nmode="{mode}"\nagents=["admin"]\n')


def budget_hooks(settings):
    return [hook for groups in settings.get("hooks", {}).values()
            for group in groups for hook in group.get("hooks", [])
            if "shantytown.admin_wake_budget" in hook.get("command", "")]


def render(root, *, name="admin", role="administrator", kit=False,
           role_settings=None, harness="claude"):
    ws = root / name
    ws.mkdir(exist_ok=True)
    if kit:
        directory = root / "provision"
        directory.mkdir(exist_ok=True)
        (directory / P.MCP_TEMPLATE).write_text('{"mcpServers":{}}')
        (directory / P.CONSENT_TEMPLATE).write_text('{"hooks":{}}')
    card = Agent(name=name, role=role, harness=harness, workspace=str(ws))
    if harness == "opencode":
        from shantytown.opencode import config_path
        path = config_path(card, root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    P.provision(card, root, settings_path=role_settings)
    path = ws / ".claude" / P.CONSENT_TEMPLATE
    return json.loads(path.read_text()) if path.is_file() else {}


@pytest.mark.parametrize("kit", [False, True])
@pytest.mark.parametrize("mode", ["advise", "enforce"])
def test_selected_projection_is_single_and_idempotent(tmp_path, kit, mode):
    configure(tmp_path, mode)
    first = render(tmp_path, kit=kit)
    second = render(tmp_path, kit=kit)
    assert len(budget_hooks(first)) == len(budget_hooks(second)) == 1
    assert first == second


def test_default_off_is_byte_identical_to_explicit_off(tmp_path):
    configure(tmp_path)
    first = render(tmp_path)
    configure(tmp_path, "off")
    assert render(tmp_path) == first
    assert budget_hooks(first) == []


@pytest.mark.parametrize("name,role", [
    ("other", "administrator"), ("admin", "worker"),
])
def test_unselected_agent_or_non_admin_has_no_budget_hook(tmp_path, name, role):
    configure(tmp_path, "advise")
    assert budget_hooks(render(tmp_path, name=name, role=role)) == []


@pytest.mark.parametrize("harness", ["codex", "opencode"])
def test_non_claude_has_no_claude_budget_hook(tmp_path, harness):
    configure(tmp_path, "advise")
    assert budget_hooks(render(tmp_path, harness=harness)) == []


def test_role_owner_prevents_duplicate_and_is_not_rewritten(tmp_path):
    configure(tmp_path, "advise")
    role = tmp_path / "administrator.settings.json"
    original = json.dumps({"hooks": {"UserPromptSubmit":
        admin_budget_prompt_hooks("administrator", tmp_path)}})
    role.write_text(original)
    identity = role.stat()
    projected = render(tmp_path, role_settings=str(role))
    assert budget_hooks(projected) == []
    assert len(budget_hooks(json.loads(role.read_text()))) == 1
    assert role.read_text() == original
    assert (role.stat().st_ino, role.stat().st_mtime_ns) == (
        identity.st_ino, identity.st_mtime_ns)


def test_deselecting_agent_removes_owned_fallback(tmp_path):
    configure(tmp_path, "advise")
    assert len(budget_hooks(render(tmp_path))) == 1
    (tmp_path / "shantytown.toml").write_text(
        '[admin_wake_budget]\nmode="advise"\nagents=["other"]\n')
    assert budget_hooks(render(tmp_path)) == []


@pytest.mark.parametrize("mode", [None, "off"])
def test_off_removes_only_owned_fallback_and_keeps_unrelated_hooks(tmp_path, mode):
    configure(tmp_path, "advise")
    assert len(budget_hooks(render(tmp_path))) == 1
    path = tmp_path / "admin/.claude" / P.CONSENT_TEMPLATE
    settings = json.loads(path.read_text())
    unrelated = {"hooks": [{"type": "command", "command": "custom-control"}]}
    settings["hooks"]["UserPromptSubmit"].append(unrelated)
    path.write_text(json.dumps(settings))
    configure(tmp_path, mode)
    after = render(tmp_path)
    assert budget_hooks(after) == []
    assert unrelated in after["hooks"]["UserPromptSubmit"]
