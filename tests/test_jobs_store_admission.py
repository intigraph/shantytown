"""Scheduler outages must be visible without the failed work store."""
import json
import subprocess
import pytest
from pathlib import Path
from types import SimpleNamespace

from shantytown import cli, jobs
from shantytown.events import FilesEvents
from shantytown.stop_event import _compose_reason, _drain
from shantytown.tier import is_governance


def fixture(root, *, retry=0):
    (root / "crew").mkdir()
    (root / "crew" / "boss.json").write_text(json.dumps({"role": "administrator"}))
    (root / "jobs").mkdir()
    (root / "jobs" / "watch.toml").write_text(
        '[trigger]\nevery="1h"\n[action]\ninbox="boss"\ndurable=true\n'
        f'message="fixture"\n[retry]\nmax={retry}\nbackoff="1s"\n')
    (root / "shantytown.toml").write_text('[env]\nSHANTY_BACKEND="seeds"\n')
    return SimpleNamespace(root=root, root_how="--root", backend=None, repo=None,
                           registry="files", jobs_sub="check", name="watch")


def test_missing_route_is_not_healthy_even_when_not_due(tmp_path, monkeypatch, capsys):
    a = fixture(tmp_path)
    monkeypatch.setenv("QUIPU_SERVER", "http://ontology.example.invalid")
    jobs.write_state(tmp_path, "watch", {"last_done": 10**12})
    assert cli._cmd_jobs(a) == cli.CANNOT_TELL
    assert "store admission failed" in capsys.readouterr().out
    assert not (tmp_path / "events").exists(), "a read check must not emit"


@pytest.mark.real_store
def test_canonical_route_beats_ambient_and_requires_positive_store_proof(tmp_path, monkeypatch, capsys):
    a = fixture(tmp_path)
    with (tmp_path / "shantytown.toml").open("a") as f:
        f.write('SHANTY_SD_QUIPU="http://board.example.invalid"\nSHANTY_SD_PREFIX="demo"\n')
    monkeypatch.setenv("SHANTY_SD_QUIPU", "http://wrong.example.invalid")
    monkeypatch.setenv("SHANTY_SD_PREFIX", "wrong")
    seen = []
    def run(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps({
            "location_source": "--quipu", "quipu_url": "http://board.example.invalid",
            "prefix": "demo"}), "")
    monkeypatch.setattr("shantytown.sd.subprocess.run", run)
    assert cli._cmd_jobs(a) == cli.OK
    assert seen == [["sd", "--quipu", "http://board.example.invalid", "where", "--json"]]
    assert "store admitted" in capsys.readouterr().out
    def unreachable(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, "", "private error text")
    monkeypatch.setattr("shantytown.sd.subprocess.run", unreachable)
    assert cli._cmd_jobs(a) == cli.CANNOT_TELL
    assert "private error text" not in capsys.readouterr().out


def test_terminal_failure_emits_once_survives_restart_and_drains_without_store(tmp_path, monkeypatch, capsys):
    a = fixture(tmp_path, retry=2)
    monkeypatch.setattr(cli, "_job_st", lambda *_: (cli.CANNOT_TELL, "private-token-like-output"))
    clock = [1000.]
    runner = cli._jobs_runner(a)
    runner.now = lambda: clock[0]
    runner.sweep()
    assert not FilesEvents(tmp_path / "events").pending("boss")
    clock[0] += 1
    runner.sweep()
    before_finish = jobs.read_state(tmp_path, "watch")
    clock[0] += 2
    runner.sweep()
    channel = FilesEvents(tmp_path / "events")
    events = channel.pending("boss")
    assert len(events) == 1 and events[0].reason == "job-failed"
    assert is_governance(events[0].reason)
    rendered = _compose_reason(events, {}, clock[0])
    assert "Scheduled job failures" in rendered and "history watch" in rendered
    assert "agent(s) stopped" not in rendered and "UNTRACKED" not in rendered
    assert "private-token-like-output" not in rendered
    _drain(channel, "boss")
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["decision"] == "block" and "history watch" in receipt["reason"]
    _drain(channel, "boss")
    assert capsys.readouterr().out == ""
    # Simulate crash after event publication, before the job's final-state write.
    jobs.write_state(tmp_path, "watch", before_finish)
    resumed = cli._jobs_runner(a)
    resumed.now = lambda: clock[0]
    resumed.sweep()
    assert channel.pending("boss") == [], "must not resurrect a consumed event"
    assert len(list((tmp_path / "events").glob("ev-*.json"))) == 1
    clock[0] += 3601
    resumed.sweep()
    clock[0] += 1
    resumed.sweep()
    clock[0] += 2
    resumed.sweep()
    assert len(channel.pending("boss")) == 1, "a later firing needs its own alert"


def test_keyed_event_does_not_overwrite_delivered_or_leave_temporary_files(tmp_path):
    channel = FilesEvents(tmp_path / "events")
    one = channel.persist("boss", "job:watch", "job-failed", False, detail="first", key="slot")
    channel.drain("boss")
    two = channel.persist("boss", "job:watch", "job-failed", False, detail="changed", key="slot")
    assert one.id == two.id and two.delivered and two.detail == "first"
    assert [p.name for p in channel.root.iterdir()] == [one.id + ".json"]


@pytest.mark.real_store
def test_real_private_store_delivery_and_unreachable_negative(tmp_path, monkeypatch):
    # Explicit SDK opt-in, with a private HOME/project/store. No ambient routing.
    from tests.test_sd_backend import _project, _sd, SD
    if SD is None:
        pytest.skip("sd not installed")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    project, store = _project(tmp_path, prefix="demo")
    root = tmp_path / "root"
    root.mkdir()
    a = fixture(root)
    with (root / "shantytown.toml").open("a") as f:
        f.write(f'SHANTY_SD_STORE={json.dumps(str(store))}\n'
                f'SHANTY_SD_PREFIX="demo"\nSHANTY_BR_REPO={json.dumps(str(project))}\n')
    monkeypatch.setattr(cli, "_panes", lambda _: SimpleNamespace(exists=lambda _: False))
    assert cli._cmd_jobs(a) == cli.OK
    runner = cli._jobs_runner(a)
    job = jobs.load(root)[0][0]
    ok, detail = runner.run_now(job)
    assert ok, detail
    rows = json.loads(_sd(project, store, "list", "--all", "--json", "--limit", "0"))
    if isinstance(rows, dict):
        rows = rows.get("issues", [])
    delivered = [r for r in rows if "[job watch] fixture" in r["title"]]
    assert len(delivered) == 1
    # Same runner/CLI path, deliberately missing explicit store, never a default.
    config = root / "shantytown.toml"
    config.write_text(config.read_text().replace(str(store), str(tmp_path / "absent.db")))
    assert cli._cmd_jobs(a) == cli.CANNOT_TELL
    failed = cli._jobs_runner(a)
    # run_now marked this interval done, so move only the injected clock.
    import time
    failed.now = lambda: time.time() + 3601
    failed.sweep()
    assert len(FilesEvents(root / "events").pending("boss")) == 1


def test_multiple_terminal_firings_in_one_queue_keep_distinct_events(tmp_path, monkeypatch):
    a = fixture(tmp_path)
    monkeypatch.setattr(cli, "_job_st", lambda *_: (cli.CANNOT_TELL, "unavailable"))
    jobs.write_state(tmp_path, "watch", {
        "last_done": 1000,
        "pending": [
            {"reason": "slot one", "queued": 1000, "attempts": 0, "retry_at": 0},
            {"reason": "slot two", "queued": 1000, "attempts": 0, "retry_at": 0}]})
    runner = cli._jobs_runner(a)
    runner.now = lambda: 1001
    runner.sweep()
    assert len(FilesEvents(tmp_path / "events").pending("boss")) == 2
