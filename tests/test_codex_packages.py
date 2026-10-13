from pathlib import Path
import os
import pytest
from shantytown import codex_packages as packages


@pytest.fixture
def disk(monkeypatch):
    monkeypatch.setattr(packages, "filesystem", lambda path: "ext4")


def test_fresh_private_packages_are_disk_backed_and_idempotent(tmp_path, disk):
    home, durable = tmp_path / "runtime", tmp_path / "disk" / "daemon"
    packages.prepare(home, durable)
    link = home / "packages" / "app-server-daemon"
    assert link.is_symlink() and link.resolve() == durable
    assert durable.stat().st_mode & 0o777 == 0o700
    (link / "release").write_bytes(b"payload")
    assert (durable / "release").read_bytes() == b"payload"
    packages.prepare(home, durable)
    assert (link / "release").read_bytes() == b"payload"


def test_existing_runtime_payload_is_preserved_without_creating_disk_target(tmp_path, disk):
    home, durable = tmp_path / "runtime", tmp_path / "disk"
    existing = home / "packages" / "app-server-daemon"
    existing.mkdir(parents=True)
    (existing / "release").write_bytes(b"live")
    with pytest.raises(RuntimeError, match="stopped-daemon migration"):
        packages.prepare(home, durable)
    assert (existing / "release").read_bytes() == b"live"
    assert not durable.exists()


@pytest.mark.parametrize("kind", ["tmpfs", "ramfs"])
def test_ram_destination_refuses_before_creation(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(packages, "filesystem", lambda path: kind)
    monkeypatch.setattr(packages.sys, "platform", "linux")
    home, durable = tmp_path / "runtime", tmp_path / "disk"
    with pytest.raises(RuntimeError, match="RAM-backed"):
        packages.prepare(home, durable)
    assert not home.exists() and not durable.exists()


def test_unknown_mount_fails_without_starting_provision(tmp_path, monkeypatch):
    def unknown(path):
        raise RuntimeError("cannot establish package destination filesystem")
    monkeypatch.setattr(packages, "filesystem", unknown)
    monkeypatch.setattr(packages.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="cannot establish"):
        packages.prepare(tmp_path / "home", tmp_path / "disk")
    assert not (tmp_path / "home").exists()


def test_foreign_link_preserves_target(tmp_path, disk):
    home = tmp_path / "runtime"
    (home / "packages").mkdir(parents=True)
    old = tmp_path / "old"
    old.mkdir()
    (home / "packages" / "app-server-daemon").symlink_to(old)
    with pytest.raises(RuntimeError, match="unexpected"):
        packages.prepare(home, tmp_path / "new")
    assert (home / "packages" / "app-server-daemon").resolve() == old
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("mode", [0o755, 0o777])
def test_nonprivate_destination_refuses_without_chmod(tmp_path, disk, mode):
    durable = tmp_path / "disk"
    durable.mkdir(mode=mode)
    durable.chmod(mode)
    with pytest.raises(RuntimeError, match="mode0700"):
        packages.prepare(tmp_path / "home", durable)
    assert durable.stat().st_mode & 0o777 == mode
    assert not (tmp_path / "home").exists()


def test_symlink_destination_refused(tmp_path, disk):
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    link = tmp_path / "disk"
    link.symlink_to(target)
    with pytest.raises(RuntimeError, match="real private"):
        packages.prepare(tmp_path / "home", link)
    assert link.is_symlink()


def test_relative_paths_refused(tmp_path, disk):
    with pytest.raises(RuntimeError, match="absolute"):
        packages.prepare(Path("relative"), tmp_path / "disk")


def test_foreign_owner_refused(tmp_path, disk, monkeypatch):
    monkeypatch.setattr(packages.os, "getuid", lambda: os.stat(tmp_path).st_uid + 1)
    with pytest.raises(RuntimeError, match="user-owned"):
        packages.prepare(tmp_path / "home", tmp_path / "disk")
    assert not (tmp_path / "home").exists()


def test_mount_reader_prefers_deepest_mount_and_decodes_spaces(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "read_text", lambda self: (
        "1 0 8:1 / / rw - ext4 /dev/a rw\n"
        "2 1 0:1 / /run rw - tmpfs tmpfs rw\n"
        "3 2 8:2 / /run/disk\\040space rw - ext4 /dev/b rw\n"))
    assert packages.filesystem(Path("/run/private")) == "tmpfs"
    assert packages.filesystem(Path("/run/disk space/child")) == "ext4"


def test_role_package_alias_is_preserved_and_refused(tmp_path, disk):
    home = tmp_path / "runtime"
    home.mkdir()
    role = tmp_path / "role"
    role.mkdir()
    (home / "packages").symlink_to(role)
    with pytest.raises(RuntimeError, match="must not share"):
        packages.prepare(home, tmp_path / "private")
    assert (home / "packages").is_symlink()
    assert list(role.iterdir()) == []
