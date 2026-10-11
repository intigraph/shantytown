import json

import pytest

from shantytown import config_source, instructions
from shantytown.config import Config
from shantytown.protocols import Agent


def cfg(text, mode="compare"):
    doc = config_source.parse(json.dumps({"version": 1, "settings": {}, "fragments": [
        {"id": "urn:test:fleet", "scope": "fleet", "selector": "", "text": text}]}))
    return Config(env={"SHANTY_INSTRUCTIONS_MODE": mode}, source_document=doc)


def test_migration_compares_bytes_and_keeps_local_identity(tmp_path):
    (tmp_path / "CLAUDE.md").write_bytes(b"exact\n")
    (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")
    identity = tmp_path / "CLAUDE.local.md"
    identity.write_bytes(b"private identity")
    for harness in ("claude", "codex", "opencode"):
        plan = instructions.prepare(tmp_path, Agent("alice", harness=harness), cfg("exact\n"))
        assert not plan.updates
        assert all(c["equal"] for c in plan.comparisons.values())
    assert identity.read_bytes() == b"private identity"


def test_compare_mode_never_overwrites_real_work(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("existing work")
    plan = instructions.prepare(tmp_path, Agent("alice"), cfg("proposed"))
    assert not plan.updates
    assert not plan.comparisons["CLAUDE.md"]["equal"]
    assert (tmp_path / "CLAUDE.md").read_text() == "existing work"


def test_apply_plan_is_one_body_and_never_a_live_external_symlink(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("old")
    (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")
    plan = instructions.prepare(tmp_path, Agent("alice"), cfg("new", "apply"))
    assert plan.updates == {tmp_path / "CLAUDE.md": "new"}
    (tmp_path / "AGENTS.md").unlink()
    (tmp_path / "AGENTS.md").symlink_to(tmp_path.parent / "outside-instructions")
    with pytest.raises(ValueError, match="leaves"):
        instructions.prepare(tmp_path, Agent("alice"), cfg("new", "apply"))


def test_no_graph_document_keeps_existing_files(tmp_path):
    assert instructions.prepare(tmp_path, Agent("alice"), Config()).updates == {}
    assert not list(tmp_path.iterdir())


def test_effective_harness_selector_comes_from_canonical_caller(tmp_path):
    doc = cfg("fleet").source_document
    doc["fragments"].append({"id": "urn:test:codex", "scope": "harness",
                             "selector": "codex", "text": "codex"})
    plan = instructions.prepare(tmp_path, Agent("alice"),
                                Config(env={"SHANTY_INSTRUCTIONS_MODE": "apply"},
                                       source_document=doc), harness="codex")
    assert set(plan.updates.values()) == {"fleetcodex"}


def test_actual_provision_consumes_one_fleet_edit_for_two_harnesses(tmp_path, monkeypatch):
    from shantytown import config, provision
    root = tmp_path / "root"; root.mkdir()
    (root / config.CONFIG_NAME).write_text(
        '[env]\nSHANTY_CONFIG_ENTITY="urn:test:config"\n'
        'SHANTY_CONFIG_SERVER="https://graph.example"\n')
    cards = []
    for name, harness in (("alice", "claude"), ("bob", "codex")):
        ws = tmp_path / name; ws.mkdir()
        (ws / "CLAUDE.md").write_text("before")
        (ws / "CLAUDE.local.md").write_text("identity")
        cards.append(Agent(name, harness=harness, workspace=str(ws)))
    for text in ("first\n", "second\n"):
        doc = cfg(text, "apply").source_document
        doc["settings"] = {"env": {"SHANTY_INSTRUCTIONS_MODE": "apply"}}
        monkeypatch.setattr(config_source, "_fetch", lambda *args: json.dumps(doc))
        for card in cards:
            provision.provision(card, root)
            ws = __import__("pathlib").Path(card.workspace)
            assert (ws / "CLAUDE.md").read_text() == text
            assert (ws / "AGENTS.md").read_text() == text
            assert (ws / "CLAUDE.local.md").read_text() == "identity"
