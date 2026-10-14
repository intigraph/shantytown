import json
import os
import fcntl

import pytest

from shantytown import codex_retention as retention


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "settings/codex/worker"
    releases = home / "packages/standalone/releases"
    releases.mkdir(parents=True)
    for version in ("0.150.0", "0.151.0", "0.152.0", "0.153.0", "0.154.0"):
        path = releases / (version + "-test-target")
        (path / "bin").mkdir(parents=True)
        (path / "bin/codex").write_bytes(b"payload" * 1000)
        (path / "codex").symlink_to("bin/codex")
        (path / "codex-package.json").write_text(json.dumps({
            "layoutVersion": 1, "version": version, "target": "test-target",
            "variant": "codex", "entrypoint": "bin/codex",
        }))
        for item in path.rglob("*"):
            os.utime(item, (1, 1), follow_symlinks=False)
        os.utime(path, (1, 1))
    (releases.parent / "current").symlink_to("releases/0.154.0-test-target")
    for name in ("auth.json", "config.toml", "history.jsonl", "state.sqlite"):
        (home / name).write_bytes(b"untouched witness")
    (home / "sessions").mkdir()
    (home / "sessions/witness").write_bytes(b"durable session")
    return home


def plan(home, keep=2, readers=lambda: set()):
    return retention.prune(home, keep, readers=readers)["plan"]


def execute(home, expected, readers=lambda: set(), keep=2):
    return retention.prune(home, keep, expected=expected, readers=readers)


def test_default_plan_is_read_only_and_execute_preserves_state(home):
    witnesses = [p for p in home.rglob("*") if p.is_file()
                 and "packages" not in p.parts]
    before = {str(p): (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns)
              for p in witnesses}
    expected = plan(home)
    assert expected["remove"] == ["0.150.0-test-target", "0.151.0-test-target"]
    assert all((home / "packages/standalone/releases" / p).exists()
               for p in expected["remove"])
    result = execute(home, expected)
    assert result["removed"] == expected["remove"] and result["freed_bytes"] > 0
    assert before == {str(p): (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns)
                      for p in witnesses}
    assert plan(home)["remove"] == []


def test_running_older_version_and_its_previous_are_retained(home):
    older = str(home / "packages/standalone/releases/0.151.0-test-target/bin/codex")
    expected = plan(home, readers=lambda: {older})
    assert expected["remove"] == []


def test_pointer_and_latest_launch_candidate_both_retained(home):
    current = home / "packages/standalone/current"
    current.unlink()
    current.symlink_to("releases/0.151.0-test-target")
    assert plan(home)["remove"] == []


def test_configurable_zero_previous_still_keeps_running_and_current(home):
    older = str(home / "packages/standalone/releases/0.151.0-test-target/bin/codex")
    expected = plan(home, 0, lambda: {older})
    assert expected["retained"] == ["0.151.0-test-target", "0.154.0-test-target"]
    assert len(expected["remove"]) == 3


@pytest.mark.parametrize("count", [-1, 21, True])
def test_invalid_count_refuses(home, count):
    with pytest.raises(retention.Refused):
        plan(home, count)


def test_fresh_payload_is_spared(home):
    old = home / "packages/standalone/releases/0.150.0-test-target/bin/codex"
    old.write_bytes(b"new build")
    assert "0.150.0-test-target" in plan(home)["retained"]


def test_external_payload_symlink_refuses_all_removal(home, tmp_path):
    p = home / "packages/standalone/releases/0.150.0-test-target/codex"
    p.unlink()
    target = tmp_path / "external"
    target.write_bytes(b"outside")
    p.symlink_to(target)
    with pytest.raises(retention.Refused):
        plan(home)
    assert target.read_bytes() == b"outside"


def test_current_escape_and_aliased_home_refuse(home, tmp_path):
    current = home / "packages/standalone/current"
    current.unlink()
    current.symlink_to(tmp_path)
    with pytest.raises(retention.Refused):
        plan(home)
    alias = tmp_path / "alias"
    alias.symlink_to(home)
    with pytest.raises(retention.Refused):
        plan(alias)


@pytest.mark.parametrize("mutation", ["payload", "current", "reader", "layout"])
def test_changed_saved_plan_cannot_delete(home, mutation):
    expected = plan(home)
    readers = lambda: set()
    root = home / "packages/standalone"
    if mutation == "payload":
        (root / "releases/0.150.0-test-target/bin/codex").write_bytes(b"changed")
    elif mutation == "current":
        (root / "current").unlink()
        (root / "current").symlink_to("releases/0.153.0-test-target")
    elif mutation == "reader":
        readers = lambda: {str(root / "releases/0.150.0-test-target/bin/codex")}
    else:
        (root / "releases/0.150.0-test-target/codex-package.json").write_text("{}")
    with pytest.raises(retention.Refused):
        execute(home, expected, readers)
    assert (root / "releases/0.150.0-test-target").exists()


def test_reader_after_atomic_detach_restores_original_package(home):
    expected = plan(home)
    root = home / "packages/standalone/releases"
    def readers():
        detached = list(root.glob(".retiring-*"))
        return {str(detached[0] / "bin/codex")} if detached else set()
    with pytest.raises(retention.Refused, match="gained a live reader"):
        execute(home, expected, readers)
    assert (root / expected["remove"][0]).exists()
    assert not list(root.glob(".retiring-*"))


def test_unknown_reader_visibility_never_deletes(home):
    expected = plan(home)
    def readers():
        raise retention.Refused("unknown process custody")
    with pytest.raises(retention.Refused):
        execute(home, expected, readers)
    assert (home / "packages/standalone/releases" / expected["remove"][0]).exists()


def test_process_executable_maps_and_open_files_are_observed(tmp_path):
    proc = tmp_path / "proc"
    pid = proc / str(os.getpid())
    (pid / "fd").mkdir(parents=True)
    (pid / "exe").symlink_to("/payload/bin/codex")
    (pid / "fd/3").symlink_to("/other/payload")
    (pid / "maps").write_text("0-1 r-xp 0 00:00 1 /mapped/payload\n")
    assert retention.process_paths(proc) == {
        "/payload/bin/codex", "/other/payload", "/mapped/payload"}
    (pid / "maps").unlink()
    with pytest.raises(retention.Refused):
        retention.process_paths(proc)


def test_command_defaults_to_plan_and_requires_matching_saved_plan(home, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(retention, "process_paths", lambda: set())
    args = ["--root", str(home.parents[2]), "--role", "worker"]
    assert retention.main(args) == 0
    expected = json.loads(capsys.readouterr().out)
    saved = tmp_path / "plan.json"
    saved.write_text(json.dumps(expected))
    assert expected["removed"] == []
    assert retention.main([*args, "--execute-plan", str(saved)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["removed"] == expected["plan"]["remove"]


def test_empty_process_namespace_is_unknown(tmp_path):
    with pytest.raises(retention.Refused, match="positive control"):
        retention.process_paths(tmp_path)


def test_unknown_release_refuses(home):
    root = home / "packages/standalone/releases"
    (root / "unexpected-evidence").mkdir()
    with pytest.raises(retention.Refused):
        plan(home)


def test_mixed_platform_refuses(home):
    root = home / "packages/standalone/releases"
    old = root / "0.150.0-test-target"
    new = root / "0.150.0-other-target"
    old.rename(new)
    metadata = json.loads((new / "codex-package.json").read_text())
    metadata["target"] = "other-target"
    (new / "codex-package.json").write_text(json.dumps(metadata))
    with pytest.raises(retention.Refused, match="mixed package"):
        plan(home)


def test_wrong_uid_or_real_current_directory_refuses(home, monkeypatch):
    uid = os.getuid()
    monkeypatch.setattr(retention.os, "getuid", lambda: uid + 1)
    with pytest.raises(retention.Refused, match="unowned"):
        plan(home)
    monkeypatch.setattr(retention.os, "getuid", lambda: uid)
    current = home / "packages/standalone/current"
    current.unlink()
    current.mkdir()
    with pytest.raises(retention.Refused, match="symlink"):
        plan(home)


def test_execution_plan_null_refuses_instead_of_dryrun_success(home, tmp_path):
    saved = tmp_path / "plan.json"
    saved.write_text('{"plan": null}')
    assert retention.main(["--root", str(home.parents[2]), "--role", "worker",
                           "--execute-plan", str(saved)]) == 2


def test_existing_cleanup_lock_refuses(home):
    fd = os.open(home / "packages/standalone", os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            plan(home)
    finally:
        os.close(fd)


def test_hardlinked_payload_survives_outside_copy_and_counts_zero(home, tmp_path):
    root = home / "packages/standalone/releases"
    payload = root / "0.150.0-test-target/bin/codex"
    witness = tmp_path / "shared-payload"
    os.link(payload, witness)
    expected = plan(home)
    # Metadata counts are unchanged by linking; only truly releasable blocks
    # contribute to the estimate, and unlink never changes the outside bytes.
    assert expected["releases"]["0.150.0-test-target"]["bytes"] < payload.stat().st_size
    execute(home, expected)
    assert witness.read_bytes() == b"payload" * 1000
