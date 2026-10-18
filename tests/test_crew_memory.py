"""Actual startup context and isolation controls; no live agent launch."""
from dataclasses import replace
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from shantytown import crew_memory as cm, session_anchor as sa
from shantytown.protocols import Agent


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    workspace = tmp_path / "crew" / "alpha_agent"
    workspace.mkdir(parents=True)
    card = Agent("alpha", workspace=str(workspace), harness="codex")
    return home, card


def memory(home, card, text="same-agent memory\n"):
    key = re.sub(r"[^a-zA-Z0-9]", "-", str(Path(card.workspace).resolve()))
    p = home / "projects" / key / "memory" / "MEMORY.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_codex_reads_original_without_copying_or_rewriting(fixture):
    home, card = fixture
    p = memory(home / ".claude", card)
    before = (p.read_bytes(), p.stat().st_mtime_ns)
    out = cm.render(card)
    assert "same-agent memory" in out and str(p) in out
    assert "complete file" in out and "Historical notes" in out
    assert (p.read_bytes(), p.stat().st_mtime_ns) == before
    assert not list(Path(card.workspace).iterdir())


def test_other_workspace_and_claude_are_not_loaded(fixture):
    home, card = fixture
    other = replace(card, name="other", workspace=str(home / "other"))
    memory(home / ".claude", other, "OTHER AGENT PRIVATE\n")
    assert cm.render(card) == ""
    memory(home / ".claude", card)
    assert cm.render(replace(card, harness="claude")) == ""
    assert cm.render(replace(card, workspace=None)) == ""


@pytest.mark.parametrize("text", ["line\n" * 201, "x" * (cm.MAX_BYTES + 100)])
def test_bounds_declare_omitted_directives_and_original_full_index(fixture, text):
    home, card = fixture
    p = memory(home / ".claude", card, text + "LATEST DIRECTIVE\n")
    out = cm.render(card)
    assert "TRUNCATED" in out and "later directives may be omitted" in out
    assert "original full index" in out and str(p) in out
    assert len(out.encode()) < cm.MAX_BYTES + 1200
    assert "complete file" not in out


def test_full_200_line_index_keeps_latest_directive(fixture):
    home, card = fixture
    memory(home / ".claude", card, "line\n" * 199 + "LATEST DIRECTIVE\n")
    out = cm.render(card)
    assert "LATEST DIRECTIVE" in out and "complete file" in out


@pytest.mark.parametrize("component", ["file", "directory"])
def test_symlink_cannot_select_another_agents_memory(fixture, component):
    home, card = fixture
    p = memory(home / ".claude", card)
    outside = home / "private"
    outside.mkdir()
    secret = outside / "MEMORY.md"
    secret.write_text("OTHER AGENT PRIVATE")
    p.unlink()
    if component == "file":
        p.symlink_to(secret)
    else:
        p.parent.rmdir()
        p.parent.symlink_to(outside, target_is_directory=True)
    out = cm.render(card)
    assert "UNKNOWN" in out and "OTHER AGENT PRIVATE" not in out


def test_invalid_utf8_is_unknown_not_silently_complete(fixture):
    home, card = fixture
    p = memory(home / ".claude", card)
    p.write_bytes(b"private\xfftext")
    assert "UNKNOWN" in cm.render(card)


def test_named_account_has_no_legacy_or_sibling_fallback(fixture, monkeypatch):
    from shantytown import accounts, account_auth, config, files
    home, card = fixture
    memory(home / ".claude", card, "LEGACY PRIVATE")
    selected_home = home / "profiles" / "selected"
    memory(home / "profiles" / "sibling", card, "SIBLING PRIVATE")
    monkeypatch.setattr(files.FilesRegistry, "get", lambda *args: card)
    cfg = SimpleNamespace(harness_by_role={}, harness_default="claude")
    monkeypatch.setattr(config, "load", lambda *args: cfg)
    monkeypatch.setattr(accounts, "selected", lambda *args: object())
    monkeypatch.setattr(account_auth, "profile", lambda *args: selected_home)
    assert cm.for_agent("/fixture", card.name) == ""
    memory(selected_home, card, "SELECTED ONLY")
    out = cm.for_agent("/fixture", card.name)
    assert "SELECTED ONLY" in out
    assert "LEGACY PRIVATE" not in out and "SIBLING PRIVATE" not in out


def test_runtime_card_not_ambient_cwd_or_account_selects_memory(fixture, monkeypatch):
    from shantytown import accounts, config, files
    home, card = fixture
    memory(home / ".claude", card)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / "foreign"))
    monkeypatch.setenv("SHANTY_ACCOUNT", "foreign")
    monkeypatch.setattr(files.FilesRegistry, "get", lambda *args: replace(card, harness=None))
    monkeypatch.setattr(config, "load", lambda *args: SimpleNamespace(
        harness_by_role={"worker": "codex"}, harness_default="claude"))
    monkeypatch.setattr(accounts, "selected", lambda *args: None)
    assert "same-agent memory" in cm.for_agent("/fixture", card.name)


def test_sessionstart_json_keeps_memory_when_tracker_is_unknown(fixture, monkeypatch, capsys):
    import io
    from shantytown import accounts, config, files
    home, card = fixture
    p = memory(home / ".claude", card, "RECOVERED MEMORY SENTINEL\n")
    monkeypatch.setenv("SHANTY_ROOT", str(home / "root"))
    monkeypatch.setenv("SHANTY_AGENT", card.name)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    monkeypatch.setattr(files.FilesRegistry, "get", lambda *args: card)
    monkeypatch.setattr(config, "load", lambda *args: SimpleNamespace(
        harness_by_role={}, harness_default="claude"))
    monkeypatch.setattr(accounts, "selected", lambda *args: None)
    monkeypatch.setattr(sa, "_run_anchor", lambda *args: (2, ""))
    assert sa.main([]) == 0
    output = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert output["hookEventName"] == "SessionStart"
    assert "could not read your plate" in output["additionalContext"]
    assert "RECOVERED MEMORY SENTINEL" in output["additionalContext"]
    assert str(p) in output["additionalContext"]


def test_actual_emitted_codex_hook_runs_and_delivers_memory_without_a_pane(fixture, tmp_path):
    import os
    import shlex
    import subprocess
    from shantytown import codex
    from shantytown.files import FilesRegistry
    home, card = fixture
    root = tmp_path / "store"
    FilesRegistry(root / "crew").set(card)
    memory(home / ".claude", card, "CODEX STARTUP MEMORY SENTINEL\n")
    emitted = codex.settings_for_role("worker", root=root)
    commands = [h["command"] for group in emitted["hooks"]["SessionStart"]
                for h in group["hooks"] if "shantytown.session_anchor" in h["command"]]
    assert len(commands) == 1
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("SHANTY_", "ST_"))}
    env.update(HOME=str(home), SHANTY_ROOT=str(root), SHANTY_AGENT=card.name,
               SHANTY_BACKEND="files", PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run(shlex.split(commands[0]), input="{}", text=True,
                            capture_output=True, env=env, timeout=15)
    assert result.returncode == 0, result.stderr
    context = json.loads(result.stdout)["hookSpecificOutput"]
    assert context["hookEventName"] == "SessionStart"
    assert "CODEX STARTUP MEMORY SENTINEL" in context["additionalContext"]
    assert sa.BANNER in context["additionalContext"]
