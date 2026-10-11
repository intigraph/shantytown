import json
import os
from pathlib import Path

import pytest

from shantytown import config, config_source as source


def document(text="fleet\n", settings=None):
    return json.dumps({"version": 1, "settings": settings or {}, "fragments": [
        {"id": "urn:test:fleet", "scope": "fleet", "selector": "", "text": text}]})


def local(entity="urn:test:config"):
    return {"env": {source.ENTITY_KEY: entity, source.SERVER_KEY: "https://graph.example"}}


def validate(value):
    config._resolve(value, Path("fixture.toml"))


def unavailable(*args):
    raise TimeoutError("a secret response body must never be printed")


def test_precise_precedence_and_backend_preserved(tmp_path):
    value = local()
    value["env"]["SHANTY_BACKEND"] = "seeds"
    projected = source.project(tmp_path, value, validate, fetch=lambda *args:
        document(settings={"env": {"SHANTY_BACKEND": "files", "SHANTY_SD_PREFIX": "demo"}}))
    assert projected.data["env"]["SHANTY_BACKEND"] == "seeds"
    assert projected.origins["env.SHANTY_BACKEND"] == "toml"
    assert projected.origins["env.SHANTY_SD_PREFIX"] == "quipu"


def test_timeout_keeps_source_bound_last_good_and_exact_render(tmp_path):
    first = source.project(tmp_path, local(), validate,
                           fetch=lambda *args: document("exact bytes\n"))
    with pytest.warns(RuntimeWarning, match="last-good"):
        cached = source.project(tmp_path, local(), validate, fetch=unavailable)
    assert cached.document == first.document
    assert source.render(cached.document, "alice", "worker", "codex") == "exact bytes\n"
    with pytest.warns(RuntimeWarning, match="local configuration"):
        other = source.project(tmp_path, local("urn:test:other"), validate, fetch=unavailable)
    assert other.document is None


def test_bad_remote_settings_cannot_poison_cache(tmp_path):
    source.project(tmp_path, local(), validate, fetch=lambda *args: document("good"))
    before = next((tmp_path / "config-source").glob("*.json")).read_bytes()
    with pytest.warns(RuntimeWarning, match="last-good"):
        projected = source.project(tmp_path, local(), validate,
            fetch=lambda *args: document(settings={"unknown_top_key": True}))
    assert source.render(projected.document, "alice", "worker", "claude") == "good"
    assert next((tmp_path / "config-source").glob("*.json")).read_bytes() == before


def test_no_opt_in_performs_no_io(tmp_path):
    result = source.project(tmp_path, {"env": {"SHANTY_BACKEND": "seeds"}}, validate,
                            fetch=lambda *args: pytest.fail("unexpected graph read"))
    assert result.document is None
    assert not list(tmp_path.iterdir())


def test_one_fragment_edit_reaches_two_agents_and_harnesses(tmp_path):
    for text in ("before\n", "after\n"):
        result = source.project(tmp_path, local(), validate, fetch=lambda *args: document(text))
        assert [source.render(result.document, name, "worker", harness)
                for name, harness in (("alice", "claude"), ("bob", "codex"))] == [text, text]


def test_scope_order_does_not_depend_on_harness_attachment():
    doc = json.loads(document("F"))
    for scope, selector, text in (("agent", "alice", "A"), ("harness", "codex", "H"),
                                  ("role", "worker", "R")):
        doc["fragments"].append({"id": "urn:test:" + scope, "scope": scope,
                                 "selector": selector, "text": text})
    parsed = source.parse(json.dumps(doc))
    assert source.render(parsed, "alice", "worker", "codex") == "FRAH"
    assert source.render(parsed, "bob", "worker", "claude") == "FR"


@pytest.mark.parametrize("payload", [
    '{"version":1,"version":1,"settings":{},"fragments":[]}',
    document(settings={"env": {"QUIPU_AUTH_TOKEN": "never persist"}}),
    document(settings={"env": {source.SERVER_KEY: "https://redirect.example"}}),
    document(settings={"env": {"SHANTY_BACKEND": "unknown"}}),
    document().replace("urn:test:fleet", 'bad>iri'),
])
def test_malformed_or_credential_document_refused(payload):
    with pytest.raises(source.SourceError):
        source.parse(payload)


def test_actual_config_reader_consumes_graph_and_reports_sources(tmp_path, monkeypatch):
    (tmp_path / config.CONFIG_NAME).write_text(
        '[env]\nSHANTY_CONFIG_ENTITY="urn:test:config"\n'
        'SHANTY_CONFIG_SERVER="https://graph.example"\n')
    monkeypatch.setattr(source, "_fetch", lambda *args:
                        document(settings={"env": {"SHANTY_BACKEND": "seeds"}}))
    loaded = config.load(tmp_path, refresh_source=True)
    assert loaded.env["SHANTY_BACKEND"] == "seeds"
    assert loaded.source_origins["env.SHANTY_BACKEND"] == "quipu"


def test_one_query_per_command_then_fresh_next_command(tmp_path, monkeypatch):
    from shantytown.deployment import command_environment
    (tmp_path / config.CONFIG_NAME).write_text(
        '[env]\nSHANTY_CONFIG_ENTITY="urn:test:config"\n'
        'SHANTY_CONFIG_SERVER="https://graph.example"\n')
    calls = []
    def fetch(*args):
        calls.append(args)
        return document(str(len(calls)))
    monkeypatch.setattr(source, "_fetch", fetch)
    with command_environment(tmp_path, refresh_config=True):
        config.load(tmp_path)
        config.load(tmp_path)
    assert len(calls) == 1
    with command_environment(tmp_path, refresh_config=True):
        loaded = config.load(tmp_path)
    assert len(calls) == 2
    assert source.render(loaded.source_document, "alice", "worker", "codex") == "2"


def test_real_reader_hydrates_typed_nodes_and_rejects_incomplete_refs(monkeypatch):
    from shantytown.answer import Answer
    class Client:
        calls = []
        missing = False
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == 1.0
            assert "root" not in kwargs  # no recursive deployment config resolution
        def _query_answer(self, query):
            self.calls.append(query)
            if len(self.calls) == 1:
                rows = [{"value": json.dumps({"version": 1, "settings": {},
                                               "fragments": ["urn:test:fleet"]})}]
            else:
                assert "VALUES ?id { <urn:test:fleet> }" in query
                assert "a <urn:test:InstructionFragment>" in query
                rows = [] if self.missing else [{"id": "urn:test:fleet", "scope": "fleet",
                                                  "selector": "", "text": "governed\n"}]
            return Answer.complete_read(rows, how="controlled transport")
    monkeypatch.setattr(source, "QuipuRegistry", Client)
    result = source.parse(source._fetch("https://graph.example", "urn:test:config",
                                        "urn:test:InstructionFragment"))
    assert source.render(result, "alice", "worker", "claude") == "governed\n"
    Client.calls.clear(); Client.missing = True
    with pytest.raises(source.SourceError, match="incomplete"):
        source._fetch("https://graph.example", "urn:test:config", "urn:test:InstructionFragment")


def test_ordinary_configuration_read_does_not_refresh_or_touch_cache(tmp_path, monkeypatch):
    source.project(tmp_path, local(), validate, fetch=lambda *args: document("last good"))
    cache = next((tmp_path / "config-source").glob("*.json"))
    before = cache.stat().st_mtime_ns
    monkeypatch.setattr(source, "_fetch", lambda *args: pytest.fail("read must not contact graph"))
    projected = source.project(tmp_path, local(), validate)
    assert source.render(projected.document, "alice", "worker", "codex") == "last good"
    assert cache.stat().st_mtime_ns == before
    assert projected.warning is None


def test_cold_read_has_no_graph_io_or_cache_write(tmp_path, monkeypatch):
    monkeypatch.setattr(source, "_fetch", lambda *args: pytest.fail("read must not contact graph"))
    with pytest.warns(RuntimeWarning, match="cache absent"):
        projected = source.project(tmp_path, local(), validate)
    assert projected.document is None
    assert not list(tmp_path.iterdir())


def test_invalid_bootstrap_cannot_silently_select_files(tmp_path):
    from argparse import Namespace
    from shantytown.cli import _backend
    (tmp_path / config.CONFIG_NAME).write_text(
        '[env]\nSHANTY_CONFIG_ENTITY="broken iri"\n'
        'SHANTY_CONFIG_SERVER="https://graph.example"\n')
    with pytest.raises(SystemExit, match="refusing a guessed backend"):
        _backend(Namespace(root=tmp_path, backend=None))


@pytest.mark.parametrize("entity", ["urn:test:config", "broken iri"])
@pytest.mark.parametrize("ambient", ["files", None])
def test_source_error_preserves_local_tracker_authority(
        tmp_path, monkeypatch, entity, ambient):
    from argparse import Namespace
    from shantytown.cli import _backend
    from shantytown.deployment import command_environment
    monkeypatch.delenv("SHANTY_BACKEND", raising=False)
    if ambient:
        monkeypatch.setenv("SHANTY_BACKEND", ambient)
    monkeypatch.setattr(source, "_fetch", lambda *a: pytest.fail("no graph read"))
    (tmp_path / config.CONFIG_NAME).write_text(
        '[env]\nSHANTY_BACKEND="seeds"\nSHANTY_CONFIG_ENTITY='
        + json.dumps(entity) + '\nSHANTY_CONFIG_SERVER="https://graph.example"\n')
    with command_environment(tmp_path):
        assert _backend(Namespace(root=tmp_path, backend=None)) == "seeds"
        assert _backend(Namespace(root=tmp_path, backend="files")) == "files"
    assert not (tmp_path / "config-source").exists()
    assert os.environ.get("SHANTY_BACKEND") == ambient


@pytest.mark.parametrize("entity", ["urn:test:config", "broken iri"])
def test_unvalidated_source_refuses_ambient_tracker_fallback(
        tmp_path, monkeypatch, entity):
    from argparse import Namespace
    from shantytown.cli import _backend
    from shantytown.deployment import command_environment
    monkeypatch.setenv("SHANTY_BACKEND", "files")
    monkeypatch.setattr(source, "_fetch", lambda *a: pytest.fail("no graph read"))
    (tmp_path / config.CONFIG_NAME).write_text(
        '[env]\nSHANTY_CONFIG_ENTITY=' + json.dumps(entity)
        + '\nSHANTY_CONFIG_SERVER="https://graph.example"\n')
    with command_environment(tmp_path):
        with pytest.raises(SystemExit, match="refusing a guessed backend"):
            _backend(Namespace(root=tmp_path, backend=None))
        assert _backend(Namespace(root=tmp_path, backend="files")) == "files"
    assert not (tmp_path / "config-source").exists()
