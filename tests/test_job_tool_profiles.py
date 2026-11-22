import hashlib
import json
import os
from pathlib import Path
import tomllib

import pytest

from shantytown import config, ephemeral as eph, job_tools as jobs, provision
from shantytown.harness import ClaudeHarness, CodexHarness
from shantytown.protocols import Agent


def profile(**kw):
    return jobs.validate_specs({"task": dict(mcp_servers=["bobbin"], skills=[], **kw)}, eph.JOBS)["task"]


def record(root, ws, harness="claude", spec=None):
    policy = config.Ephemeral(jobs={"task": spec or profile()})
    rec = {"name": "eph-task-a1b2c3", "job": "task", "harness": harness,
           "workspace": str(ws), "state": eph.LAUNCHING, "jobspec": jobs.bind(policy, "task")}
    eph.write(root, rec)
    return rec, Agent(name=rec["name"], role="worker", harness=harness, workspace=str(ws))


@pytest.mark.parametrize("raw", [
    {"typo": {}}, {"task": {"model": "x"}}, {"task": {"budget": 2}},
    {"task": {"trigger": "x"}}, {"task": {"action": "x"}},
    {"task": {"verdict": "x"}}, {"task": {"extra": []}},
    {"task": {"mcp_servers": "bobbin"}}, {"task": {"skills": ["../escape"]}},
    {"task": {"mcp_servers": ["x", "x"]}},
    {"task": {"claude_ai_connectors": "false"}},
    {"task": {"mcp_tools": {"outside": ["write"]}}},
])
def test_malformed_or_reserved_job_specs_refuse(raw):
    with pytest.raises(ValueError):
        jobs.validate_specs(raw, eph.JOBS)


def test_config_parser_and_bound_profile_are_stable_and_independent(tmp_path):
    (tmp_path / "shantytown.toml").write_text(
        '[ephemeral.jobs.task]\nmcp_servers=["bobbin"]\nskills=[]\n')
    policy = config.load(tmp_path).ephemeral
    bound = jobs.bind(policy, "task")
    assert bound["resolved"]["claude_ai_connectors"] is False
    expected = json.dumps(bound["resolved"], sort_keys=True, separators=(",", ":")).encode()
    assert bound["sha256"] == hashlib.sha256(expected).hexdigest()
    bound["resolved"]["mcp_servers"].append("foreign")
    assert policy.jobs["task"]["mcp_servers"] == ["bobbin"]
    assert jobs.bind(policy, "review") is None


def test_tampered_job_profile_cannot_select_a_broader_kit(tmp_path):
    rec, card = record(tmp_path, tmp_path / "ws")
    rec["jobspec"]["resolved"]["mcp_servers"].append("foreign")
    eph.write(tmp_path, rec)
    with pytest.raises(ValueError, match="hash mismatch"):
        jobs.selected(tmp_path, card.name)


def test_absent_job_spec_leaves_legacy_settings_and_servers_alone(tmp_path):
    card = Agent(name="eph-task-a1b2c3", harness="claude")
    eph.write(tmp_path, {"name": card.name, "job": "task"})
    assert jobs.prepare_settings(tmp_path, card, "unchanged") == "unchanged"
    assert jobs.filter_servers({"legacy": {}}, None) == {"legacy": {}}


def test_claude_profile_selects_private_settings_and_explicit_mcp_config(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    rec, card = record(tmp_path, ws)
    base = tmp_path / "shared.json"
    base.write_text('{"hooks":{"Stop":[]},"permissions":{"deny":["Write"]}}')
    before = base.read_bytes(), base.stat().st_mtime_ns
    target = Path(jobs.prepare_settings(tmp_path, card, str(base)))
    data = json.loads(target.read_text())
    assert data["disableClaudeAiConnectors"] is True
    assert data["allowedMcpServers"] == [{"serverName": "bobbin"}]
    assert data["hooks"]["Stop"] == []
    hook = data["hooks"]["PreToolUse"][-1]
    assert hook["matcher"] == "mcp__.*"
    import shlex
    import subprocess
    denied = subprocess.run(shlex.split(hook["hooks"][0]["command"]),
                            input=json.dumps({"tool_name": "mcp__foreign__write"}),
                            capture_output=True, text=True, check=True)
    assert json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert data["permissions"]["deny"] == ["Write"]
    launch = ClaudeHarness().launch(card, str(target), root=tmp_path)
    assert "ENABLE_CLAUDEAI_MCP_SERVERS=false" in launch
    assert "--strict-mcp-config --mcp-config" in launch
    assert "--disable-slash-commands" in launch
    assert (base.read_bytes(), base.stat().st_mtime_ns) == before
    assert target.stat().st_mode & 0o777 == 0o600


def test_codex_profile_and_provisioning_never_rewrite_shared_config(tmp_path, monkeypatch):
    monkeypatch.setattr(CodexHarness, "provision", lambda *a, **kw: [])
    ws = tmp_path / "ws"; ws.mkdir()
    spec = profile(mcp_tools={"bobbin": ["search"]})
    rec, card = record(tmp_path, ws, "codex", spec)
    base = tmp_path / "settings/codex/worker/config.toml"
    base.parent.mkdir(parents=True)
    base.write_text('model="fixture"\n[mcp_servers.bobbin]\nurl="http://bobbin.invalid/mcp"\n'
                    '[mcp_servers.gmail]\nurl="http://gmail.invalid/mcp"\n')
    before = base.read_bytes(), base.stat().st_mtime_ns
    target = Path(jobs.prepare_settings(tmp_path, card, str(base)))
    assert target != base
    data = tomllib.loads(target.read_text())
    assert set(data["mcp_servers"]) == {"bobbin"}
    assert data["mcp_servers"]["bobbin"]["enabled_tools"] == ["search"]
    templates = tmp_path / "provision"; templates.mkdir()
    (templates / provision.MCP_TEMPLATE).write_text(json.dumps({"mcpServers": {
        "bobbin": {"type": "http", "url": "http://bobbin.invalid/mcp"},
        "gmail": {"type": "http", "url": "http://gmail.invalid/mcp"}}}))
    assert provision.provision(card, tmp_path) == ["bobbin"]
    assert set(json.loads((ws / ".mcp.json").read_text())["mcpServers"]) == {"bobbin"}
    assert set(tomllib.loads(target.read_text())["mcp_servers"]) == {"bobbin"}
    assert tomllib.loads(target.read_text())["mcp_servers"]["bobbin"]["enabled_tools"] == ["search"]
    assert (base.read_bytes(), base.stat().st_mtime_ns) == before


def test_profile_rejects_unknown_servers_and_retains_nonlink_skills(tmp_path):
    with pytest.raises(ValueError, match="not provisioned"):
        jobs.filter_servers({}, profile())
    directory = tmp_path / ".claude/skills/personal"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("personal")
    with pytest.raises(ValueError, match="not a provisioned link"):
        jobs.prune_skills(tmp_path, profile())
    assert (directory / "SKILL.md").read_text() == "personal"


def test_only_unselected_provisioned_skill_links_are_removed(tmp_path):
    source = tmp_path / "sources"; source.mkdir()
    (source / "SKILL.md").write_text("selected")
    for runtime in (".claude", ".agents"):
        directory = tmp_path / runtime / "skills"; directory.mkdir(parents=True)
        (directory / "keep").symlink_to(source)
        (directory / "omit").symlink_to(source)
    spec = jobs.validate_specs({"task": {"skills": ["keep"]}}, eph.JOBS)["task"]
    jobs.prune_skills(tmp_path, spec)
    for runtime in (".claude", ".agents"):
        assert (tmp_path / runtime / "skills/keep").is_symlink()
        assert not (tmp_path / runtime / "skills/omit").exists()


@pytest.mark.parametrize("extra,tools,accepted", [
    ({}, ["quipu_query", "quipu_ask"], True),
    ({}, ["quipu_episode"], False),
    ({"headers": {"Authorization": "Bearer fixture"}}, ["quipu_query"], False),
    ({"headersHelper": "fixture-helper"}, ["quipu_query"], False),
    ({"command": "qp"}, ["quipu_query"], False),
    ({"env_http_headers": {"Authorization": "FIXTURE_TOKEN"}}, ["quipu_query"], False),
    ({"http_headers": {"X-API-Key": "fixture"}}, ["quipu_query"], False),
    ({"headers": {"X-Quipu-Client": "${FIXTURE_TOKEN}"}}, ["quipu_query"], False),
    ({"headers": {"X-Quipu-Client": "job-read"}}, ["quipu_query"], True),
    ({"future_auth_option": "fixture"}, ["quipu_query"], False),
    ({"url": "https://fixture:secret@quipu.example.invalid/mcp"}, ["quipu_query"], False),
    ({"url": "https://quipu.example.invalid/mcp?token=fixture"}, ["quipu_query"], False),
])
def test_only_explicit_anonymous_read_tools_use_the_headerless_job_rail(extra, tools, accepted):
    spec = jobs.validate_specs({"review": {"mcp_servers": ["quipu-read"],
                "mcp_tools": {"quipu-read": tools}}}, eph.JOBS)["review"]
    servers = {"quipu-read": {"url": "https://quipu.example.invalid/mcp", **extra}}
    assert bool(jobs.anonymous_read_servers(servers, spec)) is accepted
    assert jobs.anonymous_read_servers(servers, None) == set()


def test_direct_quipu_writer_credential_is_not_copied_into_a_job(tmp_path):
    spec = jobs.validate_specs({"task": {"mcp_servers": ["quipu-read"],
        "mcp_tools": {"quipu-read": ["quipu_query"]}}}, eph.JOBS)["task"]
    with pytest.raises(ValueError, match="anonymous read-only"):
        jobs.filter_servers({"quipu-read": {"url": "https://quipu.example.invalid/mcp",
                             "headersHelper": "writer-helper"}}, spec)


def test_anonymous_quipu_profile_can_be_provisioned_without_a_bearer(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    spec = jobs.validate_specs({"task": {"mcp_servers": ["quipu-read"],
        "mcp_tools": {"quipu-read": ["quipu_query", "quipu_ask"]}}}, eph.JOBS)["task"]
    rec, card = record(tmp_path, ws, spec=spec)
    templates = tmp_path / "provision"; templates.mkdir()
    (templates / provision.MCP_TEMPLATE).write_text(json.dumps({"mcpServers": {
        "quipu-read": {"type": "http", "url": "https://quipu.example.invalid/mcp"},
        "gmail": {"type": "http", "url": "https://mail.example.invalid/mcp"}}}))
    assert provision.provision(card, tmp_path) == ["quipu-read"]
    actual = json.loads((ws / ".mcp.json").read_text())["mcpServers"]
    assert actual == {"quipu-read": {"type": "http", "url": "https://quipu.example.invalid/mcp"}}


def test_claude_tool_guard_enforces_exact_names_and_never_grants(tmp_path):
    spec = profile(mcp_tools={"bobbin": ["search"]})
    rec, card = record(tmp_path, tmp_path / "ws", spec=spec)
    assert jobs.tool_decision(tmp_path, card.name, {"tool_name": "mcp__bobbin__search"}) == {}
    assert jobs.tool_decision(tmp_path, card.name, {"tool_name": "Read"}) == {}
    for tool in ("mcp__bobbin__write", "mcp__gmail__search", "mcp__bobbin__search_extra", ""):
        decision = jobs.tool_decision(tmp_path, card.name, {"tool_name": tool})
        assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    rec["jobspec"]["sha256"] = "tampered"
    eph.write(tmp_path, rec)
    assert jobs.tool_decision(tmp_path, card.name, {"tool_name": "mcp__bobbin__search"})["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_profiled_protected_launch_refuses_before_touching_operator_staging(tmp_path, monkeypatch, capsys):
    from shantytown import cli, job_launch
    root = tmp_path / "root"
    (root / "crew").mkdir(parents=True)
    (root / "crew/boss.json").write_text(json.dumps({
        "role": "administrator", "pane": "fixture-boss", "dangerous": True}))
    (root / "shantytown.toml").write_text(
        '[ephemeral]\nunattended=true\nrequire_verified_identity=true\nunattended_uid_ready=true\n'
        '[ephemeral.jobs.task]\nmcp_servers=[]\nskills=[]\n')
    monkeypatch.setattr(cli, "_spawn_actor", lambda **kw: "boss")
    monkeypatch.setattr(cli, "_spawn_inside", lambda *a, **kw: None)
    monkeypatch.setattr(job_launch, "select", lambda *a, **kw: pytest.fail("staging must stay untouched"))
    monkeypatch.setattr(cli, "_launch", lambda *a, **kw: pytest.fail("must not launch"))
    rc = cli.main(["--root", str(root), "agent", "spawn", "--ephemeral", "--job", "task", "--item", "fixture-item"])
    assert rc == cli.REFUSED
    assert "qualified protected-UID projection" in capsys.readouterr().err
    assert eph.records(root) == []


TRIAGE_VERDICTS = ["diagnosed", "needs-owner", "unknown", "blocked"]


def test_job_verdicts_bind_per_job_and_absent_keeps_the_legacy_enum():
    specs = jobs.validate_specs({"triage": {"verdicts": TRIAGE_VERDICTS},
                                 "task": {}}, eph.JOBS)
    assert specs["triage"]["verdicts"] == TRIAGE_VERDICTS
    assert "verdicts" not in specs["task"]          # existing binding hashes stay stable
    assert eph.job_verdicts({"jobspec": {"resolved": specs["triage"]}}) == tuple(TRIAGE_VERDICTS)
    assert eph.job_verdicts({"jobspec": {"resolved": specs["task"]}}) == eph.VERDICTS
    assert eph.job_verdicts({}) == eph.VERDICTS


@pytest.mark.parametrize("job,verdicts", [
    ("triage", ["diagnosed"]),                      # blocked is mandatory
    ("triage", ["diagnosed", "blocked", "failed"]), # failed belongs to st teardown
    ("triage", []), ("triage", "blocked"),
    ("review", ["approve", "blocked", "lgtm"]),     # gated jobs never rename
    ("merge", ["shipped", "blocked"]),
])
def test_bad_job_verdicts_refuse(job, verdicts):
    with pytest.raises(ValueError):
        jobs.validate_specs({job: {"verdicts": verdicts}}, eph.JOBS)


def test_gated_jobs_may_narrow_the_legacy_verdicts():
    spec = jobs.validate_specs({"review": {"verdicts": ["approve", "request-changes", "blocked"]}},
                               eph.JOBS)["review"]
    assert spec["verdicts"] == ["approve", "request-changes", "blocked"]


def test_prompt_names_the_jobs_own_verdicts_and_legacy_prompt_is_unchanged():
    import time
    base = {"name": "eph-triage-a1b2c3", "job": "triage", "item": "it-1",
            "deadline": time.time() + 600, "administrator": "boss", "max_turns": 2,
            "attempt": 1, "repo": None, "pr": None}
    legacy = eph.prompt(dict(base))
    assert "approve|request-changes|merged|blocked|done|failed" in legacy
    assert "configured verdicts" not in legacy
    spec = jobs.validate_specs({"triage": {"verdicts": TRIAGE_VERDICTS}}, eph.JOBS)["triage"]
    custom = eph.prompt(dict(base, jobspec={"resolved": spec, "sha256": "x"}))
    assert "diagnosed|needs-owner|unknown|blocked" in custom
    assert "configured verdicts are diagnosed|needs-owner|unknown|blocked" in custom
