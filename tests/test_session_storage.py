"""The fleet opt-in must refuse loudly, without moving an existing session."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess

import pytest

from shantytown import session_storage as storage
from shantytown.harness import get
from shantytown.protocols import Agent


@pytest.mark.parametrize("device,root,kind,available", [
    ((8, 1), (8, 1), "ext4", 1000),
    ((8, 2), (8, 1), "ext4", 1000),
    ((8, 3), (8, 1), "tmpfs", 1000),
    ((8, 3), (8, 1), "ramfs", 1000),
    ((8, 3), (8, 1), "ext4", 99),
])
def test_observed_root_wrong_device_ram_or_low_space_refuse(device, root, kind, available):
    with pytest.raises(RuntimeError):
        storage.validate_observation(device, (8, 3), root, kind, available, 100)


def test_observed_disk_positive_control():
    storage.validate_observation((8, 3), (8, 3), (8, 1), "ext4", 100, 100)


@pytest.mark.parametrize("root,mount,device,minimum", [
    ("relative", "/disk", "8:3", "100"),
    ("/disk", "/disk", "8:3", "100"),
    ("/elsewhere/logs", "/disk", "8:3", "100"),
    ("/disk/../logs", "/disk", "8:3", "100"),
    ("/disk/logs", "/disk", "unknown", "100"),
    ("/disk/logs", "/disk", "8:3", "0"),
])
def test_configuration_cannot_guess(root, mount, device, minimum):
    with pytest.raises(ValueError):
        storage.parse(root, mount, device, minimum)


def test_partial_configuration_refuses(monkeypatch):
    monkeypatch.setenv("SHANTY_CODEX_SESSIONS_ROOT", "/disk/sessions")
    with pytest.raises(ValueError):
        storage.configured()


def test_absent_configuration_keeps_legacy_default():
    assert storage.configured() is None


def test_real_unmounted_destination_blocks_launch_and_creates_nothing(tmp_path):
    mount = tmp_path / "not-mounted"
    mount.mkdir()
    destination = mount / "logs"
    config = storage.Storage(destination, mount, (8, 3), 100)
    marker = tmp_path / "daemon-started"
    result = subprocess.run(
        ["sh", "-c", config.command() + " && touch " + str(marker)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2 and "REFUSED" in result.stderr
    assert not destination.exists() and not marker.exists()


@pytest.fixture
def disk(tmp_path, monkeypatch):
    """Private fixture only; real mount admission has independent negative controls."""
    mount = tmp_path / "disk"
    mount.mkdir(mode=0o700)
    config = storage.Storage(mount / "logs" / "agent" / "sessions", mount, (8, 3), 100)
    @contextmanager
    def fixture_admission(_):
        fd = os.open(mount, os.O_RDONLY | os.O_DIRECTORY)
        try:
            yield fd
        finally:
            os.close(fd)
    monkeypatch.setattr(storage, "admitted", fixture_admission)
    monkeypatch.setattr(Path, "is_mount", lambda path: path == mount)
    home = tmp_path / "run"
    home.mkdir()
    return config, home


def test_fresh_prepare_is_idempotent_and_writes_through(disk):
    config, home = disk
    storage.prepare(config, home)
    storage.prepare(config, home)
    (home / "sessions" / "rollout.jsonl").write_text("record")
    assert (config.root / "rollout.jsonl").read_text() == "record"
    assert (home / "sessions").readlink() == config.root
    assert config.root.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("kind", ["directory", "other-link", "broken-link", "file"])
def test_existing_history_custody_is_never_replaced_or_copied(disk, tmp_path, kind):
    config, home = disk
    link = home / "sessions"
    history = tmp_path / "old-history"
    history.mkdir()
    record = history / "rollout.jsonl"
    record.write_text("retained history")
    if kind == "directory":
        link.mkdir()
        (link / "old.jsonl").write_text("old")
    elif kind in {"other-link", "broken-link"}:
        link.symlink_to(history if kind == "other-link" else tmp_path / "absent")
    else:
        link.write_text("old")
    before = link.lstat()
    with pytest.raises(RuntimeError):
        storage.prepare(config, home)
    assert link.lstat() == before
    assert record.read_text() == "retained history"
    assert not config.root.exists()


def test_destination_symlink_is_not_followed(disk, tmp_path):
    config, home = disk
    external = tmp_path / "outside"
    external.mkdir()
    (config.mount / "logs").symlink_to(external)
    with pytest.raises(OSError):
        storage.prepare(config, home)
    assert list(external.iterdir()) == []
    assert not (home / "sessions").exists()


def test_nonprivate_existing_destination_is_preserved_and_refused(disk):
    config, home = disk
    (config.mount / "logs").mkdir(mode=0o755)
    with pytest.raises(RuntimeError):
        storage.prepare(config, home)
    assert (config.mount / "logs").stat().st_mode & 0o777 == 0o755
    assert not (home / "sessions").exists()


def test_launch_guards_before_stop_and_sets_up_after_stop(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    (root / "shantytown.toml").write_text('''[env]
SHANTY_REMOTE_CONTROL = "true"
SHANTY_CODEX_SESSIONS_ROOT = "/disk/crew-sessions"
SHANTY_CODEX_SESSIONS_MOUNT = "/disk"
SHANTY_CODEX_SESSIONS_DEVICE = "8:3"
SHANTY_CODEX_SESSIONS_MIN_FREE = "100"
''')
    config = root / "settings" / "codex" / "worker" / "config.toml"
    binary = config.parent / "packages" / "standalone" / "current" / "codex"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    launch = get("codex").launch(Agent(name="sample", role="worker"), str(config), root=root)
    first = launch.index("-m shantytown.session_storage")
    stop = launch.index("remote-control stop")
    second = launch.index("-m shantytown.session_storage", first + 1)
    start = launch.index("remote-control start")
    assert first < stop < second < start
    assert "--root /disk/crew-sessions/sample/sessions" in launch
    assert "cp -an" not in launch
    assert "--home" not in launch[first:stop].split(" && ")[0]
    # compose/dry-run must never create the operator's mount or state root.
    assert not (tmp_path / "disk").exists()


@pytest.mark.parametrize("remote,managed", [(False, True), (True, False)])
def test_configured_storage_never_falls_back_to_local(tmp_path, remote, managed, capsys):
    from shantytown.harness import Unsupported
    root = tmp_path / "store"
    root.mkdir()
    (root / "shantytown.toml").write_text(f'''[env]
SHANTY_REMOTE_CONTROL = "{str(remote).lower()}"
SHANTY_CODEX_SESSIONS_ROOT = "/disk/crew-sessions"
SHANTY_CODEX_SESSIONS_MOUNT = "/disk"
SHANTY_CODEX_SESSIONS_DEVICE = "8:3"
SHANTY_CODEX_SESSIONS_MIN_FREE = "100"
''')
    config = root / "settings" / "codex" / "worker" / "config.toml"
    if managed:
        binary = config.parent / "packages" / "standalone" / "current" / "codex"
        binary.parent.mkdir(parents=True)
        binary.write_text("")
    with pytest.raises(Unsupported, match="refusing local fallback"):
        get("codex").launch(Agent(name="sample", role="worker"), str(config), root=root)
    assert "launching local" not in capsys.readouterr().err


def test_symlinked_mount_refuses_without_creating_logs(tmp_path):
    mount = tmp_path / "alias"
    actual = tmp_path / "actual"
    actual.mkdir()
    mount.symlink_to(actual)
    config = storage.Storage(mount / "sessions", mount, (8, 3), 100)
    with pytest.raises(RuntimeError):
        with storage.admitted(config):
            pytest.fail("symlinked mount admitted")
    assert list(actual.iterdir()) == []


def test_nonlinux_opt_in_refuses_cleanly(monkeypatch, tmp_path):
    monkeypatch.setattr(storage.sys, "platform", "unsupported-platform")
    config = storage.Storage(tmp_path / "sessions", tmp_path, (8, 3), 100)
    with pytest.raises(RuntimeError, match="Linux only"):
        with storage.admitted(config):
            pytest.fail("unsupported platform admitted")
