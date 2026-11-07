"""Source agreement, not agreement between two equally stale projections."""
import copy
import json
import tomllib

import pytest

from shantytown import provision as P, tooling as T
from shantytown.answer import Answer
from shantytown.protocols import Agent
from shantytown.quipu import QuipuUnreachable, QuipuQueryRejected


IRI = "urn:example:tooling"
DATA = {
    "version": 1,
    "mcpServers": {"search": {"type": "http", "url": "https://example.invalid/mcp",
                              "headers": {"Authorization": "Bearer ${SEARCH_TOKEN}"}}},
    "skills": {"search": "canonical/search"},
    "instructions": "Query the knowledge service before starting a task.",
}


@pytest.fixture
def kit(tmp_path, monkeypatch):
    root = tmp_path / "store"
    root.mkdir()
    (root / "shantytown.toml").write_text(f'[env]\nSHANTY_TOOLING_MANIFEST = "{IRI}"\n')
    (root / "provision").mkdir()
    (root / "provision" / P.CONSENT_TEMPLATE).write_text('{}')
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "canonical/search").mkdir(parents=True)
    (ws / "canonical/search/SKILL.md").write_text("# Search\n")
    (ws / "CLAUDE.md").write_text("General Claude guidance.\n")
    (ws / "AGENTS.md").write_text("General Codex guidance.\n")
    config = root / "settings/codex/agent-worker/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('model = "example"\n[mcp_servers.old]\ncommand = "old"\n')
    monkeypatch.setenv("SEARCH_TOKEN", "test-secret")
    data = copy.deepcopy(DATA)
    calls = []
    def query(self, text):
        calls.append(text)
        return Answer.complete_read([{"value": json.dumps(data)}], how="fixture")
    monkeypatch.setattr(T.QuipuRegistry, "_query_answer", query)
    return root, ws, config, data, calls


def card(ws, harness="codex"):
    return Agent(name="worker", workspace=str(ws), harness=harness)


def test_both_harnesses_project_graph_and_preserve_other_instructions(kit):
    root, ws, config, data, calls = kit
    for harness in ("claude", "codex"):
        assert P.provision(card(ws, harness), root) == ["search"]
        assert P.missing_kit(card(ws, harness), root) == []
    assert (ws / "CLAUDE.md").read_text().startswith("General Claude guidance.")
    assert (ws / "AGENTS.md").read_text().startswith("General Codex guidance.")
    for name in ("CLAUDE.md", "AGENTS.md"):
        assert (ws / name).read_text().count(T.BEGIN) == 1
        assert data["instructions"] in (ws / name).read_text()
    cfg = tomllib.loads(config.read_text())
    assert cfg["model"] == "example"
    assert set(cfg["mcp_servers"]) == {"search"}, "removed servers must be removed from Codex too"
    # aegis-6qau3t: the bearer is a literal in the 0600 config, never an export.
    assert cfg["mcp_servers"]["search"]["http_headers"]["Authorization"] == "Bearer test-secret"
    assert "bearer_token_env_var" not in cfg["mcp_servers"]["search"]
    assert config.stat().st_mode & 0o777 == 0o600
    assert (ws / ".mcp.json").stat().st_mode & 0o777 == 0o600
    assert all(f"<{IRI}>" in q for q in calls)


def test_endpoint_and_instruction_changes_detected_without_name_changes(kit):
    root, ws, config, data, _ = kit
    P.provision(card(ws), root)
    data["mcpServers"]["search"]["url"] = "https://changed.invalid/mcp"
    data["instructions"] = "Updated canonical guidance."
    gaps = P.missing_kit(card(ws), root)
    assert "mcp(Quipu drift)" in gaps
    assert "codex-mcp(Quipu drift)" in gaps
    assert "instructions(Quipu drift)" in gaps
    P.provision(card(ws), root)
    assert P.missing_kit(card(ws), root) == []


def test_doctor_uses_one_fresh_snapshot_for_entire_report(kit):
    root, ws, _, _, calls = kit
    P.provision(card(ws), root)
    calls.clear()
    report, broken = P.uniformity_report([card(ws), card(ws, "claude")], root)
    assert not broken, report
    assert len(calls) == 1


def test_first_class_config_launch_survives_outage_without_caching_credentials(kit, monkeypatch):
    from shantytown import config_source
    root, ws, _, _, _ = kit
    with (root / "shantytown.toml").open("a") as stream:
        stream.write('SHANTY_CONFIG_ENTITY="urn:example:config"\n'
                     'SHANTY_CONFIG_SERVER="https://graph.example"\n'
                     'SHANTY_CONFIG_FRAGMENT_CLASS="urn:example:InstructionFragment"\n')
    document = json.dumps({"version": 1, "settings": {}, "fragments": [
        {"id": "urn:example:fleet", "scope": "fleet", "selector": "", "text": "fleet"}]})
    monkeypatch.setattr(config_source, "_fetch", lambda *args: document)
    assert P.provision(card(ws, "claude"), root) == ["search"]
    def unavailable(*args):
        raise QuipuUnreachable("controlled outage")
    monkeypatch.setattr(config_source, "_fetch", unavailable)
    monkeypatch.setattr(T.QuipuRegistry, "_query_answer", unavailable)
    with pytest.warns(RuntimeWarning, match="last-good"):
        assert P.provision(card(ws, "claude"), root) == ["search"]
    assert all("test-secret" not in path.read_text()
               for path in (root / "config-source").glob("*.json"))
    # The old graph-authoritative contract remains default, even with a cache.
    with pytest.raises(T.ToolingError):
        T.load(root)


@pytest.mark.parametrize("result", [[], [{"value": "{}"}, {"value": "{}"}],
                                    [{"value": {}}], [{"wrong": "{}"}]])
def test_missing_or_ambiguous_graph_is_not_local_fallback(kit, monkeypatch, result):
    root, ws, _, _, _ = kit
    (root / "provision" / P.MCP_TEMPLATE).write_text(json.dumps({"mcpServers": DATA["mcpServers"]}))
    before = (ws / "AGENTS.md").read_bytes()
    monkeypatch.setattr(T.QuipuRegistry, "_query_answer", lambda *a: Answer.complete_read(result, how="fixture"))
    with pytest.raises(P.ProvisionError):
        P.provision(card(ws), root)
    assert not (ws / ".mcp.json").exists()
    assert (ws / "AGENTS.md").read_bytes() == before
    assert P.missing_kit(card(ws), root) == ["tooling-source(UNKNOWN)"]


@pytest.mark.parametrize("failure", ["unreachable", "truncated", "rejected"])
def test_unknown_doctor_never_reports_uniform(kit, monkeypatch, failure):
    root, ws, _, _, _ = kit
    def query(*args):
        if failure == "unreachable":
            raise QuipuUnreachable("sensitive upstream body")
        if failure == "rejected":
            raise QuipuQueryRejected("sensitive upstream body")
        return Answer.capped([{"value": json.dumps(DATA)}], how="fixture", caveat="cap")
    monkeypatch.setattr(T.QuipuRegistry, "_query_answer", query)
    report, broken = P.uniformity_report([card(ws)], root)
    assert broken and "UNKNOWN" in report
    assert "sensitive" not in report


def test_secret_rotation_and_wrong_skill_destination_are_drift(kit, monkeypatch):
    root, ws, _, _, _ = kit
    P.provision(card(ws), root)
    monkeypatch.setenv("SEARCH_TOKEN", "rotated-secret")
    other = ws / "other"
    other.mkdir()
    (other / "SKILL.md").write_text("wrong source")
    link = ws / ".agents/skills/search"
    link.unlink()
    link.symlink_to(other)
    gaps = P.missing_kit(card(ws), root)
    assert "mcp(Quipu drift)" in gaps
    assert ".agents-skills(search)" in gaps
    assert "secret" not in str(gaps)


def test_reverse_rulebook_symlink_does_not_become_a_loop(kit):
    root, ws, _, _, _ = kit
    (ws / "CLAUDE.md").unlink()
    (ws / "CLAUDE.md").symlink_to("AGENTS.md")
    P.provision(card(ws), root)
    assert not (ws / "AGENTS.md").is_symlink()
    assert (ws / "CLAUDE.md").read_bytes() == (ws / "AGENTS.md").read_bytes()
    assert P.missing_kit(card(ws), root) == []


@pytest.mark.parametrize("obstruction", ["skill", "override", "marker", "missing-source"])
def test_refuses_obstructions_before_writing_mcp(kit, obstruction):
    root, ws, _, _, _ = kit
    if obstruction == "skill":
        (ws / ".agents/skills/search").mkdir(parents=True)
        (ws / ".agents/skills/search/SKILL.md").write_text("personal work")
    elif obstruction == "override":
        (ws / "AGENTS.override.md").write_text("shadows AGENTS")
    elif obstruction == "marker":
        (ws / "CLAUDE.md").write_text(T.BEGIN)
    else:
        (ws / "canonical/search/SKILL.md").unlink()
    with pytest.raises(P.ProvisionError):
        P.provision(card(ws), root)
    assert not (ws / ".mcp.json").exists()


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(version=True),
    lambda d: d.update(instructions=""),
    lambda d: d.update(skills={"../escape": "/tmp"}),
    lambda d: d.update(extra="typo"),
    lambda d: d["mcpServers"]["search"].update(headers={"Authorization": "Bearer literal-secret"}),
])
def test_invalid_manifest_refused_without_echoing_content(mutation):
    data = copy.deepcopy(DATA)
    mutation(data)
    with pytest.raises(T.ToolingError) as error:
        T.parse(json.dumps(data), IRI)
    assert "literal-secret" not in str(error.value)


def test_duplicate_keys_refused():
    with pytest.raises(T.ToolingError, match="duplicate"):
        T.parse('{"version":1,"version":2}', IRI)


def test_source_iri_cannot_inject_sparql(kit, monkeypatch):
    root, _, _, _, calls = kit
    (root / "shantytown.toml").write_text('[env]\nSHANTY_TOOLING_MANIFEST = "urn:x> ?s ?p ?o"\n')
    with pytest.raises(T.ToolingError, match="IRI"):
        T.load(root)
    assert calls == []


def test_removed_skill_is_detected_and_retracted_but_personal_skill_survives(kit):
    root, ws, _, data, _ = kit
    P.provision(card(ws), root)
    personal = ws / ".agents/skills/personal"
    personal.mkdir()
    (personal / "SKILL.md").write_text("personal")
    data["skills"] = {}
    assert "skills(retired in Quipu)" in P.missing_kit(card(ws), root)
    P.provision(card(ws), root)
    assert not (ws / ".agents/skills/search").exists()
    assert not (ws / ".claude/skills/search").exists()
    assert (personal / "SKILL.md").read_text() == "personal"
    assert P.missing_kit(card(ws), root) == []


def test_explicit_secret_argument_verifies_against_same_values(kit, monkeypatch):
    root, ws, _, _, _ = kit
    monkeypatch.delenv("SEARCH_TOKEN")
    P.provision(card(ws), root, secrets={"SEARCH_TOKEN": "explicit"})
    assert "explicit" in (ws / ".mcp.json").read_text()


def test_retire_final_server_and_quote_credentials(kit, monkeypatch):
    root, ws, config, data, _ = kit
    token = 'quoted"credential\\with\nnewline'
    monkeypatch.setenv("SEARCH_TOKEN", token)
    P.provision(card(ws), root)
    assert json.loads((ws / ".mcp.json").read_text())["mcpServers"]["search"]["headers"]["Authorization"] == "Bearer " + token
    assert token not in config.read_text()
    data["mcpServers"] = {}
    assert P.provision(card(ws), root) == []
    assert tomllib.loads(config.read_text()).get("mcp_servers", {}) == {}
    assert P.missing_kit(card(ws), root) == []


def test_actual_query_carries_attribution_and_rejects_truncation(tmp_path, monkeypatch):
    from io import BytesIO
    monkeypatch.setenv("SHANTY_TOOLING_MANIFEST", IRI)
    seen = []
    def response(request, timeout):
        seen.append(request)
        return BytesIO(json.dumps({"rows": [{"value": json.dumps(DATA)}], "truncated": True}).encode())
    monkeypatch.setattr("urllib.request.urlopen", response)
    with pytest.raises(T.ToolingError, match="truncated"):
        T.load(tmp_path)
    assert seen[0].get_header("X-quipu-client") == "shantytown-tooling"
    assert json.loads(seen[0].data)["verbose"] is True


def test_claude_consent_follows_manifest_changes(kit):
    root, ws, _, data, _ = kit
    (root / "provision" / P.CONSENT_TEMPLATE).write_text(json.dumps({
        "enabledMcpjsonServers": ["retired"], "permissions": {"deny": ["ExampleTool"]}}))
    P.provision(card(ws, "claude"), root)
    path = ws / ".claude" / P.CONSENT_TEMPLATE
    consent = json.loads(path.read_text())
    assert consent["enabledMcpjsonServers"] == ["search"]
    assert consent["permissions"]["deny"] == ["ExampleTool"]
    consent["enabledMcpjsonServers"] = []
    path.write_text(json.dumps(consent))
    assert "mcp-consent(Quipu drift)" in P.missing_kit(card(ws, "claude"), root)


def test_explicit_disabled_server_refuses_before_any_projection(kit):
    root, ws, _, _, _ = kit
    (root / "provision" / P.CONSENT_TEMPLATE).write_text('{"disabledMcpjsonServers":["search"]}')
    with pytest.raises(P.ProvisionError, match="disabled"):
        P.provision(card(ws, "claude"), root)
    assert not (ws / ".mcp.json").exists()
    assert T.BEGIN not in (ws / "CLAUDE.md").read_text()


def _cron_repoint(ws, name):
    """Reproduce what aegis's */30 relink-skills.sh does to the claude half:
    it points <ws>/.claude/skills/<name> at the clone's OWN skills/<name>."""
    source = ws / "skills" / name
    source.mkdir(parents=True, exist_ok=True)
    (source / "SKILL.md").write_text("# from the workspace\n")
    link = ws / ".claude/skills" / name
    link.unlink()
    link.symlink_to(source)
    return source


def test_retiring_a_skill_survives_the_cron_repointed_claude_link(kit):
    """aegis-adttz8: a */30 cron re-points the claude half at the clone's own
    skills/ source. That is a target shantytown itself produces, so retiring the
    skill must be an ordinary retirement, not a launch refusal."""
    root, ws, _, data, _ = kit
    P.provision(card(ws), root)
    source = _cron_repoint(ws, "search")
    data["skills"] = {}
    assert "skills(retired in Quipu)" in P.missing_kit(card(ws), root)
    P.provision(card(ws), root)
    assert not (ws / ".claude/skills/search").exists()
    assert not (ws / ".agents/skills/search").exists()
    # the workspace source is never touched — only the link is retracted
    assert (source / "SKILL.md").is_file()
    assert P.missing_kit(card(ws), root) == []


def test_retiring_a_skill_still_refuses_a_foreign_link(kit, tmp_path):
    """The relaxation is scoped to the workspace's own skills/ source. Any other
    target is still 'personal changes' and must still refuse."""
    root, ws, _, data, _ = kit
    P.provision(card(ws), root)
    foreign = tmp_path / "elsewhere/search"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("# hand-made\n")
    link = ws / ".claude/skills/search"
    link.unlink()
    link.symlink_to(foreign)
    data["skills"] = {}
    assert "skills(receipt or retired link unreadable)" in P.missing_kit(card(ws), root)
    with pytest.raises(P.ProvisionError, match="personal changes"):
        P.provision(card(ws), root)


def test_host_roots_project_all_skills_and_preserve_legacy_projection(kit, tmp_path, monkeypatch):
    root, ws, _, data, _ = kit
    roots = {key: tmp_path / key.lower() for key in T.SKILL_ROOTS}
    monkeypatch.setenv("SHANTY_SKILL_SOURCE_ROOT", str(tmp_path / "wrong-ambient-root"))
    sources = {f"skill{i:02}": f"${{SHANTY_SKILL_SOURCE_ROOT}}/skills/skill{i:02}"
               for i in range(26)}
    sources["camayoc"] = "${CAMAYOC_SRC}/camayoc/skills/camayoc"
    absolute = {}
    with (root / "shantytown.toml").open("a") as stream:
        for key, path in roots.items():
            stream.write(f'{key} = {json.dumps(str(path))}\n')
    for name, source in sources.items():
        key, suffix = source[2:].split("}/", 1)
        target = roots[key] / suffix
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text(f"# {name}\n")
        absolute[name] = str(target)
    data["skills"] = {name: str(tmp_path / "foreign-host" / name) for name in sources}
    assert sum(not (path / "SKILL.md").is_file()
               for _, path in T.load(root).sources(ws)) == 27
    with pytest.raises(P.ProvisionError, match="canonical skill source unavailable"):
        P.provision(card(ws, "claude"), root)
    assert not (ws / T.RECEIPT).exists()
    print("foreign-host baseline: 27/27 unavailable; projection refused")
    data["skills"] = absolute
    assert P.provision(card(ws, "claude"), root) == ["search"]
    assert len(list((ws / ".claude/skills").iterdir())) == 27
    before = {p.relative_to(ws): p.read_bytes() for p in
              [ws / T.RECEIPT, ws / ".mcp.json", ws / "CLAUDE.md", ws / "AGENTS.md"]}
    data["skills"] = sources
    assert P.provision(card(ws, "claude"), root) == ["search"]
    assert len(list((ws / ".claude/skills").iterdir())) == 27
    assert P.missing_kit(card(ws, "claude"), root) == []
    assert all(p.read_bytes() == before[p.relative_to(ws)] for p in
               [ws / T.RECEIPT, ws / ".mcp.json", ws / "CLAUDE.md", ws / "AGENTS.md"])
    print("first host: 27/27 projected; receipt, MCP and instructions byte-identical")
    # A second host binds the SAME governed JSON to its own source trees.
    with (root / "shantytown.toml").open("w") as stream:
        stream.write(f'[env]\nSHANTY_TOOLING_MANIFEST = "{IRI}"\n')
        for key in roots:
            path = tmp_path / "second-host" / key.lower()
            stream.write(f'{key} = {json.dumps(str(path))}\n')
            for source in sources.values():
                if source.startswith('${' + key + '}/'):
                    target = path / source.split('}/', 1)[1]
                    target.mkdir(parents=True)
                    (target / "SKILL.md").write_text("# local source\n")
    assert P.provision(card(ws, "claude"), root) == ["search"]
    assert len(list((ws / ".claude/skills").iterdir())) == 27
    assert P.missing_kit(card(ws, "claude"), root) == []
    assert all("second-host" in str(link.resolve())
               for link in (ws / ".claude/skills").iterdir())
    print("second host: 27/27 projected from local roots; same safety check")
    missing = next((ws / ".claude/skills").iterdir()).resolve() / "SKILL.md"
    missing.unlink()
    before = (ws / T.RECEIPT).read_bytes()
    with pytest.raises(P.ProvisionError, match="canonical skill source unavailable"):
        P.provision(card(ws, "claude"), root)
    assert (ws / T.RECEIPT).read_bytes() == before


@pytest.mark.parametrize("path", ["${HOME}/skill", "$HOME/skill", "${CAMAYOC_SRC}/../skill",
                                 "${CAMAYOC_SRC}//absolute", "${CAMAYOC_SRC}/${OTHER}"])
def test_skill_root_references_refuse_unknown_expansion_and_escape(path):
    data = copy.deepcopy(DATA)
    data["skills"] = {"skill": path}
    with pytest.raises(T.ToolingError):
        T.parse(json.dumps(data), IRI)


@pytest.mark.parametrize("value", [None, "relative/root", "/tmp/../elsewhere", "${OTHER}/root"])
def test_invalid_or_missing_host_root_refuses_before_projection(kit, monkeypatch, value):
    root, ws, _, data, _ = kit
    monkeypatch.delenv("SHANTY_SKILL_SOURCE_ROOT", raising=False)
    if value is not None:
        with (root / "shantytown.toml").open("a") as stream:
            stream.write(f'SHANTY_SKILL_SOURCE_ROOT = {json.dumps(value)}\n')
    data["skills"] = {"skill": "${SHANTY_SKILL_SOURCE_ROOT}/skills/skill"}
    before = (ws / "CLAUDE.md").read_bytes()
    with pytest.raises(P.ProvisionError):
        P.provision(card(ws, "claude"), root)
    assert (ws / "CLAUDE.md").read_bytes() == before
    assert not (ws / T.RECEIPT).exists()
