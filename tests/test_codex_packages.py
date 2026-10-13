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


@pytest.mark.parametrize('mask', [0o002, 0o077])
def test_fresh_home_shared_parent_is_explicitly_private_under_umask(tmp_path, disk, mask):
    home = tmp_path / 'runtime'
    durable = tmp_path / 'fresh-home' / '.local' / 'share' / 'cache' / 'packages' / 'daemon'
    old_mask = os.umask(mask)
    try:
        packages.prepare(home, durable)
    finally:
        os.umask(old_mask)
    assert durable.parent.stat().st_mode & 0o777 == 0o700
    assert durable.stat().st_mode & 0o777 == 0o700
    assert durable.parent.stat().st_uid == os.getuid()
    assert (home / 'packages' / 'app-server-daemon').resolve() == durable
    packages.prepare(home, durable)


def test_existing_nonprivate_shared_parent_refuses_without_chmod_or_payload_creation(tmp_path, disk):
    parent = tmp_path / 'packages'
    parent.mkdir(mode=0o775)
    parent.chmod(0o775)
    sentinel = parent / 'retained'
    sentinel.write_bytes(b'preserve')
    identity = parent.stat().st_mtime_ns
    with pytest.raises(RuntimeError, match='verify its ownership'):
        packages.prepare(tmp_path / 'runtime', parent / 'daemon')
    assert parent.stat().st_mode & 0o777 == 0o775
    assert parent.stat().st_mtime_ns == identity
    assert sentinel.read_bytes() == b'preserve'
    assert not (parent / 'daemon').exists()
    assert not (tmp_path / 'runtime').exists()


def test_shared_parent_symlink_refuses_without_touching_real_target(tmp_path, disk):
    target = tmp_path / 'private'
    target.mkdir(mode=0o700)
    parent = tmp_path / 'packages'
    parent.symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError, match='shared package parent must be a real'):
        packages.prepare(tmp_path / 'runtime', parent / 'daemon')
    assert list(target.iterdir()) == []
    assert parent.is_symlink()


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


def test_two_cards_share_one_payload_and_native_install_lock(tmp_path, disk):
    durable = tmp_path / "disk"
    packages.prepare(tmp_path / "first", durable)
    packages.prepare(tmp_path / "second", durable)
    first = tmp_path / "first" / "packages" / "app-server-daemon"
    second = tmp_path / "second" / "packages" / "app-server-daemon"
    (first / "install.lock").write_bytes(b"lock")
    (first / "release").write_bytes(b"payload")
    assert (first / "install.lock").stat().st_ino == (second / "install.lock").stat().st_ino
    assert (second / "release").read_bytes() == b"payload"
    assert first.resolve() == second.resolve() == durable


def old_package(home):
    root = home / "packages" / "app-server-daemon"
    binary = root / "releases" / "version" / "bin" / "codex"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"reviewed payload")
    binary.chmod(0o755)
    (root / "current").symlink_to("releases/version")
    (root / "install.lock").write_bytes(b"")
    return root


@pytest.fixture
def stopped(monkeypatch, disk):
    monkeypatch.setattr(packages, "quarantine_custody", lambda root: {"coverage": "ESTABLISHED"})


def test_stopped_migration_shares_verified_bytes_and_retains_native_lock(tmp_path, stopped):
    first, second = tmp_path / "first", tmp_path / "second"
    old1, old2 = old_package(first), old_package(second)
    parent = tmp_path / "shared"
    parent.mkdir(mode=0o700)
    durable = parent / "daemon"
    expected = packages.manifest(old1)
    packages.migrate_stopped(first, durable)
    native_inode = (durable / "install.lock").stat().st_ino
    packages.migrate_stopped(second, durable)
    assert old1.is_symlink() and old2.is_symlink()
    assert packages.manifest(durable) == expected
    assert (durable / "install.lock").stat().st_ino == native_inode
    assert (old1 / "current/bin/codex").read_bytes() == b"reviewed payload"
    for home in (first, second):
        retained = [p for p in home.glob("packages/.stopped-daemon-*") if p.is_dir()]
        assert len(retained) == 1
        assert (retained[0] / "current/bin/codex").read_bytes() == b"reviewed payload"
        import json
        receipt = json.loads(retained[0].with_name(retained[0].name + ".json").read_text())
        assert receipt["coverage"] == "ESTABLISHED" and receipt["soak"].startswith("HOLD")
        assert receipt["home"] == str(home) and receipt["quarantine"] == str(retained[0])


def test_fresh_prepare_parent_also_passes_stopped_migration_guard(tmp_path, stopped):
    import shutil
    fresh, old_home = tmp_path / 'fresh-card', tmp_path / 'stopped-card'
    durable = tmp_path / 'new-home' / '.local' / 'share' / 'cache' / 'packages' / 'daemon'
    old = old_package(old_home)
    previous = os.umask(0o002)
    try:
        packages.prepare(fresh, durable)
    finally:
        os.umask(previous)
    assert durable.parent.stat().st_mode & 0o777 == 0o700
    # Populate payload contents without copytree copying the old root's mode
    # onto the already private shared destination (the native updater retains it).
    for entry in old.iterdir():
        target = durable / entry.name
        if entry.is_symlink():
            target.symlink_to(os.readlink(entry))
        elif entry.is_dir():
            shutil.copytree(entry, target, symlinks=True)
        else:
            shutil.copy2(entry, target)
    assert durable.stat().st_mode & 0o777 == 0o700
    expected = packages.manifest(old)
    packages.migrate_stopped(old_home, durable)
    assert old.is_symlink() and old.resolve() == durable
    assert packages.manifest(durable) == expected
    retained = list(old.parent.glob('.stopped-daemon-*'))
    assert any(path.is_dir() and (path / 'current/bin/codex').read_bytes() == b'reviewed payload'
               for path in retained)


def test_live_package_refuses_before_copy(tmp_path, disk, monkeypatch):
    home = tmp_path / "home"
    old = old_package(home)
    def live(root):
        raise RuntimeError("daemon package still has a live executable reference")
    monkeypatch.setattr(packages, "quarantine_custody", live)
    with pytest.raises(RuntimeError, match="live executable"):
        packages.migrate_stopped(home, tmp_path / "disk" / "daemon")
    assert old.is_dir() and not old.is_symlink()
    assert not (tmp_path / "disk").exists()


def test_shared_version_mismatch_preserves_old_directory(tmp_path, stopped):
    home = tmp_path / "home"
    old = old_package(home)
    parent = tmp_path / "disk"
    parent.mkdir(mode=0o700)
    durable = parent / "daemon"
    durable.mkdir(mode=0o700)
    (durable / "different").write_bytes(b"retained")
    with pytest.raises(RuntimeError, match="shared package differs"):
        packages.migrate_stopped(home, durable)
    assert old.is_dir() and not old.is_symlink()
    assert (durable / "different").read_bytes() == b"retained"


def test_copy_corruption_preserves_source_and_removes_only_own_stage(tmp_path, stopped, monkeypatch):
    home = tmp_path / "home"
    old = old_package(home)
    parent = tmp_path / "disk"
    parent.mkdir(mode=0o700)
    original = packages.shutil.copytree
    def corrupt(source, destination, *args, **options):
        value = original(source, destination, *args, **options)
        if Path(source) == old:
            (Path(destination) / "releases/version/bin/codex").write_bytes(b"corrupt")
        return value
    monkeypatch.setattr(packages.shutil, "copytree", corrupt)
    with pytest.raises(RuntimeError, match="copy integrity"):
        packages.migrate_stopped(home, parent / "daemon")
    assert (old / "current/bin/codex").read_bytes() == b"reviewed payload"
    assert not (parent / "daemon").exists()
    assert not [path for path in parent.glob(".daemon-package-*") if path.is_dir()]


def test_late_reference_retains_backup_after_link_switch(tmp_path, stopped, monkeypatch):
    home = tmp_path / "home"
    old = old_package(home)
    parent = tmp_path / "disk"
    parent.mkdir(mode=0o700)
    def custody(root):
        if root.name.startswith(".stopped-daemon-"):
            raise RuntimeError("late live reference")
    monkeypatch.setattr(packages, "quarantine_custody", custody)
    with pytest.raises(RuntimeError, match="late live"):
        packages.migrate_stopped(home, parent / "daemon")
    assert old.is_symlink()
    backups = list(old.parent.glob(".stopped-daemon-*"))
    assert len(backups) == 1
    assert (backups[0] / "current/bin/codex").read_bytes() == b"reviewed payload"


def test_manifest_normalizes_internal_absolute_current_link(tmp_path):
    old = old_package(tmp_path / "home")
    (old / "current").unlink()
    (old / "current").symlink_to(old / "releases/version")
    assert packages.manifest(old)["current"] == ["link", "releases/version"]


def test_manifest_refuses_external_payload_link(tmp_path):
    old = old_package(tmp_path / "home")
    (old / "external").symlink_to(tmp_path)
    with pytest.raises(RuntimeError, match="escapes"):
        packages.manifest(old)


def test_actual_open_descriptor_positive_control(tmp_path):
    root = tmp_path / "payload"
    root.mkdir()
    file = root / "held"
    file.write_bytes(b"held")
    with file.open("rb"):
        with pytest.raises(RuntimeError, match="open descriptor"):
            packages.assert_quiescent(root)


def test_native_installer_lock_contention_refuses_without_changing_card(tmp_path, stopped):
    home = tmp_path / "home"
    old = old_package(home)
    parent = tmp_path / "disk"
    parent.mkdir(mode=0o700)
    durable = parent / "daemon"
    packages.shutil.copytree(old, durable, symlinks=True)
    durable.chmod(0o700)
    with (durable / "install.lock").open("a+b") as held:
        packages.fcntl.flock(held, packages.fcntl.LOCK_EX | packages.fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            packages.migrate_stopped(home, durable)
    assert old.is_dir() and not old.is_symlink()


@pytest.fixture
def proc_fixture(tmp_path, monkeypatch):
    proc = tmp_path / "12345"
    proc.mkdir()
    (proc / "status").write_text("Uid: " + " ".join([str(os.getuid())] * 4) + "\n")
    (proc / "fd").mkdir()
    (proc / "maps").write_text("")
    original = Path.iterdir
    monkeypatch.setattr(Path, "iterdir", lambda path: iter([proc]) if path == Path("/proc") else original(path))
    return proc


def test_missing_exe_still_checks_existing_descriptor(tmp_path, proc_fixture):
    payload = tmp_path / "payload"
    payload.mkdir()
    file = payload / "held"
    file.write_bytes(b"held")
    (proc_fixture / "fd/3").symlink_to(file)
    with pytest.raises(RuntimeError, match="open descriptor"):
        packages.assert_quiescent(payload)


def test_missing_exe_still_checks_mapped_payload(tmp_path, proc_fixture):
    payload = tmp_path / "payload"
    payload.mkdir()
    file = payload / "held"
    file.write_bytes(b"held")
    (proc_fixture / "maps").write_text(f"1-2 r-xp 0 0:1 1 {file}\n")
    with pytest.raises(RuntimeError, match="mapped reference"):
        packages.assert_quiescent(payload)


def test_existing_process_with_missing_metadata_refuses(tmp_path, proc_fixture):
    (proc_fixture / "status").unlink()
    with pytest.raises(RuntimeError, match="metadata custody is UNKNOWN"):
        packages.assert_quiescent(tmp_path / "payload")


def test_confirmed_exited_process_is_not_a_live_reference(tmp_path, proc_fixture):
    packages.shutil.rmtree(proc_fixture)
    packages.assert_quiescent(tmp_path / "payload")


def test_malformed_uid_is_unknown_not_a_foreign_process(tmp_path, proc_fixture):
    (proc_fixture / "status").write_text("Uid:\n")
    with pytest.raises(RuntimeError, match="UID custody is UNKNOWN"):
        packages.assert_quiescent(tmp_path / "payload")


@pytest.fixture
def protected(proc_fixture, monkeypatch):
    proc = proc_fixture
    (proc / "comm").write_text("ssh-agent\n")
    (proc / "cmdline").write_bytes(b"/usr/bin/ssh-agent\0")
    (proc / "stat").write_text("12345 (ssh-agent) " + " ".join(["S"] + ["0"] * 18 + ["123"]) + "\n")
    read_text = Path.read_text
    def denied(path, *args, **kwargs):
        if path == proc / "maps":
            raise PermissionError("protected")
        return read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", denied)
    return proc


def test_identified_protected_process_permits_retention_only(tmp_path, protected):
    root = tmp_path / "payload"
    report = packages.quarantine_custody(root)
    assert report["coverage"] == "BOUNDED" and report["deletion"] == "HOLD"
    assert report["protected"] == [{"pid": 12345, "comm": "ssh-agent",
                                    "start_ticks": 123, "denied": ["maps"], "coverage": "BOUNDED"}]
    with pytest.raises(RuntimeError, match="custody is UNKNOWN"):
        packages.assert_quiescent(root)


@pytest.mark.parametrize("argv", [b"/usr/bin/codex\0", b"/usr/bin/worker\0PAYLOAD\0"])
def test_protected_payload_consumer_is_hold(tmp_path, protected, argv):
    root = tmp_path / "payload"
    (protected / "cmdline").write_bytes(argv.replace(b"PAYLOAD", os.fsencode(root)))
    with pytest.raises(RuntimeError, match="plausible payload consumer"):
        packages.quarantine_custody(root)


def test_protected_unknown_identity_is_hold(tmp_path, protected):
    (protected / "stat").write_text("malformed")
    with pytest.raises(RuntimeError, match="custody is UNKNOWN"):
        packages.quarantine_custody(tmp_path / "payload")


def test_protected_unreadable_cmdline_is_hold(tmp_path, protected, monkeypatch):
    original = Path.open
    def denied(path, *args, **kwargs):
        if path == protected / "cmdline":
            raise PermissionError("protected")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(RuntimeError, match="custody is UNKNOWN"):
        packages.quarantine_custody(tmp_path / "payload")


def test_denied_maps_does_not_hide_readable_payload_descriptor(tmp_path, protected):
    root = tmp_path / "payload"
    root.mkdir()
    (root / "held").write_bytes(b"held")
    (protected / "fd/3").symlink_to(root / "held")
    with pytest.raises(RuntimeError, match="open descriptor"):
        packages.quarantine_custody(root)


def test_retained_absolute_links_restore_at_stopped_rollback(tmp_path, stopped):
    home = tmp_path / "home"
    old = old_package(home)
    (old / "current").unlink()
    (old / "current").symlink_to(old / "releases/version")
    parent = tmp_path / "disk"
    parent.mkdir(mode=0o700)
    packages.migrate_stopped(home, parent / "daemon")
    backup, = (p for p in old.parent.glob(".stopped-daemon-*") if p.is_dir())
    assert (backup / "releases/version/bin/codex").read_bytes() == b"reviewed payload"
    old.unlink()
    backup.rename(old)
    assert (old / "current/bin/codex").read_bytes() == b"reviewed payload"
    assert (parent / "daemon/current/bin/codex").read_bytes() == b"reviewed payload"


def test_protected_pid_reuse_is_hold(tmp_path, protected, monkeypatch):
    original = Path.read_text
    count = 0
    def reused(path, *args, **kwargs):
        nonlocal count
        result = original(path, *args, **kwargs)
        if path == protected / "stat":
            count += 1
            if count > 1:
                result = result.replace("123\n", "124\n")
        return result
    monkeypatch.setattr(Path, "read_text", reused)
    with pytest.raises(RuntimeError, match="identity changed"):
        packages.quarantine_custody(tmp_path / "payload")
