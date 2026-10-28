"""Prime contract: real CLI in isolated roots plus shared-anchor and deadline controls."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from shantytown import cli, prime

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "from shantytown.cli import main; raise SystemExit(main())"


def snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns,
            p.read_bytes() if p.is_file() else None) for p in root.rglob("*")}


def run(root, args):
    home = root / "home"
    home.mkdir(exist_ok=True)
    env = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
           "XDG_CACHE_HOME": str(home / "cache"), "XDG_DATA_HOME": str(home / "data"),
           "PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT),
           "PYTHONDONTWRITEBYTECODE": "1", "SHANTY_AGENT": "worker"}
    return subprocess.run([sys.executable, "-B", "-c", ENTRY, *args],
                          cwd=root, env=env, capture_output=True, text=True, timeout=5)


def value(result):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def world(root, *, count=2):
    store = root / "store"
    crew = store / "crew"
    crew.mkdir(parents=True)
    for i in range(count):
        name = "worker" if i == 0 else f"peer-{i:03d}"
        (crew / f"{name}.json").write_text(json.dumps({
            "role": "worker", "harness": "codex"}))
    items = store / "items"
    items.mkdir()
    (items / "task.json").write_text(json.dumps({"title": "Fixture work", "status": "open",
                                               "assignee": "worker", "priority": 1}))
    return store


def test_missing_store_keeps_primer_and_creates_nothing(tmp_path):
    (tmp_path / "home").mkdir()
    before = snapshot(tmp_path)
    v = value(run(tmp_path, ["--root", str(tmp_path / "absent"), "prime", "--json"]))
    assert v["schema"] == "stack-prime/1" and v["tool"] == "st" and v["version"]
    assert v["live"]["status"] == "absent" and v["status"] == "degraded"
    assert "## Agent workflow" in v["primer"]["text"]
    assert v["live"]["summary"]["crew"] is None
    assert snapshot(tmp_path) == before


def test_actual_cli_is_read_only_and_caps_roster(tmp_path):
    store = world(tmp_path, count=24)
    (tmp_path / "home").mkdir()
    before = snapshot(tmp_path)
    v = value(run(tmp_path, ["--root", str(store), "--registry", "files", "--backend", "files",
                             "prime", "--json"]))
    live = v["live"]
    assert live["status"] == "ok", v
    assert live["elapsed_ms"] < 1000
    summary = live["summary"]
    assert summary["crew"]["total"] == 24 and summary["crew"]["truncated"]
    assert len(summary["crew"]["members"]) == prime.MEMBER_CAP
    assert summary["anchor"]["agent"] == "worker"
    assert summary["anchor"]["current_work"]["id"] == "task"
    assert summary["lead"] is None
    assert snapshot(tmp_path) == before, "prime published plate or changed bytes/mtime/paths"


@pytest.mark.parametrize("tail", [[], ["--static"]])
def test_brief_is_five_to_ten_lines(tmp_path, tail):
    result = run(tmp_path, ["--root", str(tmp_path / "absent"), "prime", "--brief", *tail])
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert 5 <= len(lines) <= 10
    assert lines[0].startswith("st ") and lines[-1] == "Run `st prime` for the full primer."


def test_brief_json_omits_text_and_static_ignores_broken_configuration(tmp_path):
    store = world(tmp_path)
    (store / "shantytown.toml").write_text("not = [valid")
    v = value(run(tmp_path, ["--root", str(store), "prime", "--static", "--brief", "--json"]))
    assert v["live"]["status"] == "skipped" and v["status"] == "ok"
    assert "text" not in v["primer"]
    assert v["live"]["elapsed_ms"] == 0


def test_section_is_static_prefix_matched_and_usage_errors_are_two(tmp_path):
    v = value(run(tmp_path, ["prime", "--section", "aGeNt", "--json"]))
    assert v["primer"]["text"].startswith("## Agent workflow\n")
    assert "## Core commands" not in v["primer"]["text"]
    assert v["live"]["status"] == "skipped"
    for args in [["--section", "missing"], ["--unsupported"], ["--brief", "--section", "What"]]:
        result = run(tmp_path, ["prime", *args])
        assert result.returncode == 2


def test_unreachable_registry_is_named_without_falling_back(tmp_path):
    store = world(tmp_path)
    (store / "shantytown.toml").write_text(
        '[env]\nQUIPU_SERVER = "http://127.0.0.1:1"\nSHANTY_ONTO_NS = "https://example.test/crew/"\n')
    v = value(run(tmp_path, ["--root", str(store), "--registry", "quipu", "prime", "--json"]))
    assert v["live"]["status"] == "unreachable", v
    assert v["live"]["summary"]["anchor"] is None, "fell back to available files card"
    assert v["status"] == "degraded"


def test_live_config_error_is_not_clean_empty_state(tmp_path):
    store = world(tmp_path)
    (store / "shantytown.toml").write_text("not = [valid")
    v = value(run(tmp_path, ["--root", str(store), "prime", "--json"]))
    assert v["live"]["status"] == "unreadable"
    assert v["live"]["summary"]["crew"] is None


def test_static_does_not_probe_git_config_identity_or_anchor(monkeypatch, capsys):
    import shantytown
    from shantytown import deployment, actor_identity

    def forbidden(*args, **kwargs):
        raise AssertionError("static orientation ran a live probe")

    monkeypatch.setattr(shantytown, "deployed_sha", forbidden)
    monkeypatch.setattr(deployment, "resolve_root", forbidden)
    monkeypatch.setattr(actor_identity, "authenticated_actor", forbidden)
    monkeypatch.setattr(cli, "_resolve_anchor", forbidden)
    assert cli.main(["prime", "--static", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["live"]["status"] == "skipped"


def test_version_probes_git_only_when_requested(monkeypatch, capsys):
    import shantytown
    calls = []
    monkeypatch.setattr(shantytown, "deployed_sha", lambda: calls.append(True) or "fixture")
    cli.build_parser()
    assert calls == []
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["--version"])
    assert exc.value.code == 0 and calls == [True]
    assert "(fixture)" in capsys.readouterr().out


def test_prime_reuses_startup_anchor_read_and_never_publication(tmp_path, monkeypatch):
    from shantytown import actor_identity
    from shantytown.tmux import NullPanes
    store = world(tmp_path)
    args = argparse.Namespace(root=store, registry="files", backend="files", repo=None, me="worker")
    monkeypatch.setattr(actor_identity, "authenticated_actor", lambda: None)
    monkeypatch.setattr(cli, "_panes", lambda a: NullPanes())
    (store / "crew/worker.json").write_text(json.dumps({
        "role": "worker", "harness": "codex", "reports_to": "lead"}))
    (store / "crew/lead.json").write_text(json.dumps({"role": "administrator"}))
    monkeypatch.setattr(cli, "_lead_status", lambda *a: lambda name: True)

    def forbidden(*args, **kwargs):
        raise AssertionError("prime published the plate")

    monkeypatch.setattr(cli.plate_publish, "publish", forbidden)
    calls = []
    resolve = cli._resolve_anchor

    def shared(a, me, **kwargs):
        calls.append(me)
        return resolve(a, me, **kwargs)

    monkeypatch.setattr(cli, "_resolve_anchor", shared)
    anchored, _, _ = resolve(args, "worker")
    before = snapshot(tmp_path)
    result = prime.live_snapshot(args)
    assert calls == ["worker"]
    assert result["summary"]["anchor"]["current_work"]["id"] == anchored.item.id
    assert result["summary"]["anchor"]["role"] == anchored.me.role
    assert result["summary"]["lead"]["agent"] == anchored.lead.name
    assert result["summary"]["lead"]["reachable"] == anchored.lead_up is True
    assert result["summary"]["administrator"] == anchored.admin == "lead"
    assert snapshot(tmp_path) == before


def test_slow_child_is_cut_short_and_reaped(monkeypatch, tmp_path):
    actual = subprocess.Popen
    children = []

    def slow(*args, **kwargs):
        child = actual([sys.executable, "-c", "import time; time.sleep(10)"], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(prime.subprocess, "Popen", slow)
    args = argparse.Namespace(root=tmp_path, registry="files", backend="files", repo=None, me="worker")
    started = time.monotonic()
    result = prime.probe(args)
    assert result["status"] == "partial" and result["summary"]["anchor"] is None
    assert result["elapsed_ms"] < 1000 and time.monotonic() - started < 1
    assert children[0].poll() is not None


def test_oversize_protocol_response_is_not_an_empty_success(monkeypatch, tmp_path):
    actual = subprocess.Popen
    children = []

    def noisy(*args, **kwargs):
        child = actual([sys.executable, "-c", "import sys; sys.stdout.write('x' * 100000)"], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(prime.subprocess, "Popen", noisy)
    result = prime.probe(argparse.Namespace(root=tmp_path, registry=None, backend=None, repo=None, me=None))
    assert result["status"] == "unreadable" and result["summary"]["crew"] is None
    assert children[0].poll() is not None


def test_generated_skill_docs_and_packaged_primer_match():
    spec = importlib.util.spec_from_file_location("sync_primer", ROOT / "scripts/sync-primer.py")
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    source = (ROOT / "shantytown/primer.md").read_text()
    assert prime.primer() == source
    assert prime.sections(source) == ["What Shantytown is", "Agent workflow", "Core commands",
                                      "MCP tools", "Next steps"]
    for path, depth in [(ROOT / "docs/prime.md", 1), (ROOT / "skills/shantytown/SKILL.md", 2)]:
        text = path.read_text()
        assert sync.generated(text, source, depth) == text, "run python3 scripts/sync-primer.py"
    import tomllib
    package = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]
    assert "primer.md" in package["shantytown"]



def test_actual_cli_times_out_a_slow_registry(tmp_path):
    import socket
    import threading
    store = world(tmp_path)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(2)
        port = listener.getsockname()[1]
        (store / "shantytown.toml").write_text(
            f'[env]\nQUIPU_SERVER = "http://127.0.0.1:{port}"\n'
            'SHANTY_ONTO_NS = "https://example.test/crew/"\n')

        def slow():
            try:
                conn, _ = listener.accept()
                with conn:
                    conn.recv(8192)
                    time.sleep(1.2)
            except OSError:
                pass

        thread = threading.Thread(target=slow, daemon=True)
        thread.start()
        started = time.monotonic()
        result = value(run(tmp_path, ["--root", str(store), "--registry", "quipu",
                                       "prime", "--json"]))
        elapsed = time.monotonic() - started
        assert result["live"]["status"] == "partial", result
        assert elapsed < 1, "deadline must include CLI startup"
        assert result["live"]["elapsed_ms"] < 1000
        assert result["live"]["summary"]["crew"] is None
        thread.join(timeout=2)



def test_prime_disables_seeds_read_cache_writes(tmp_path, monkeypatch):
    from shantytown import actor_identity, seeds_read_cache
    from shantytown.anchor import Anchoring
    from shantytown.files import FilesRegistry
    from shantytown.protocols import Agent
    store = world(tmp_path)
    monkeypatch.setattr(actor_identity, "authenticated_actor", lambda: None)
    touched = []

    def directory():
        touched.append(True)
        raise OSError("cache directory would be created")

    monkeypatch.setattr(seeds_read_cache, "_directory", directory)

    def resolve(a, me, *, require_complete):
        assert require_complete
        assert seeds_read_cache.read(
            "http://example.test", "SELECT", 1, opener=None,
            fetch=lambda: {"rows": []}, validate=lambda v: None) == {"rows": []}
        return Anchoring(Agent(name=me), None, None, None, [], []), None, FilesRegistry(store / "crew")

    monkeypatch.setattr(cli, "_resolve_anchor", resolve)
    result = prime.live_snapshot(argparse.Namespace(root=store, registry="files", backend="files",
                                                    repo=None, me="worker"))
    assert result["status"] == "ok" and not touched
