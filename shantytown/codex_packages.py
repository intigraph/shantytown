"""Keep daemon payloads in one disk package outside Linux runtime tmpfs without live deletion."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import shutil
import tempfile
import time
import os
from pathlib import Path
import stat
import sys


def filesystem(path: Path) -> str:
    """Resolve the deepest enclosing Linux mount, including escaped names."""
    def unescape(value: str) -> str:
        for old, new in (("\\040", " "), ("\\011", "\t"),
                         ("\\012", "\n"), ("\\134", "\\")):
            value = value.replace(old, new)
        return value
    matches = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        left, right = line.split(" - ", 1)
        mount = Path(unescape(left.split()[4]))
        if path == mount or mount in path.parents:
            matches.append((len(mount.parts), right.split()[0]))
    if not matches:
        raise RuntimeError("cannot establish package destination filesystem")
    return max(matches)[1]


def prepare(home: Path, durable: Path) -> None:
    """Create a shared user-private disk destination; refuse existing payload custody."""
    if not durable.is_absolute() or not home.is_absolute():
        raise RuntimeError("package paths must be absolute")
    link = home / "packages" / "app-server-daemon"
    if link.parent.is_symlink():
        raise RuntimeError("daemon package parent must not share a role package directory")
    # Never replace a real directory or an unexpected link. Existing releases
    # need an explicit stopped-daemon migration, outside launch provisioning.
    if link.is_symlink():
        if link.resolve() != durable.resolve():
            raise RuntimeError("unexpected daemon package link; preserve it")
    elif link.exists():
        raise RuntimeError("existing daemon packages require a stopped-daemon migration")
    ancestor = durable
    while not ancestor.exists():
        ancestor = ancestor.parent
    if sys.platform.startswith("linux") and filesystem(ancestor.resolve()) in {"tmpfs", "ramfs"}:
        raise RuntimeError("daemon package destination is RAM-backed")
    if durable.is_symlink():
        raise RuntimeError("daemon package destination must be a real private directory")
    durable.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = durable.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError("daemon package destination must be user-owned mode0700")
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.is_symlink():
        link.symlink_to(durable, target_is_directory=True)



def assert_quiescent(root: Path) -> None:
    """Refuse any same-user executable, mapping or descriptor under this tree."""
    if not sys.platform.startswith("linux"):
        raise RuntimeError("stopped package custody cannot be verified on this platform")
    prefix = str(root.resolve()) + os.sep
    def inside(value):
        value = value.removesuffix(" (deleted)")
        return value == str(root.resolve()) or value.startswith(prefix)
    processes = sorted(Path("/proc").iterdir(), key=lambda p: p.name != str(os.getpid()))
    if len(processes) > 8192:
        raise RuntimeError("process custody exceeds its bounded inventory")
    deadline = time.monotonic() + 15
    for proc in processes:
        if time.monotonic() > deadline:
            raise RuntimeError("process custody exceeded its deadline")
        if not proc.name.isdecimal():
            continue
        try:
            status = (proc / "status").read_text()
            uid_line = next((line for line in status.splitlines() if line.startswith("Uid:")), None)
            if uid_line is None:
                raise RuntimeError("process UID custody is UNKNOWN")
            if os.getuid() not in [int(value) for value in uid_line.split()[1:]]:
                continue
            try:
                executable = os.readlink(proc / "exe")
            except FileNotFoundError:
                continue  # exited process or a kernel thread
            if inside(executable):
                raise RuntimeError("daemon package still has a live executable reference")
            for descriptor in (proc / "fd").iterdir():
                try:
                    if inside(os.readlink(descriptor)):
                        raise RuntimeError("daemon package still has an open descriptor")
                except FileNotFoundError:
                    continue
            for line in (proc / "maps").read_text().splitlines():
                parts = line.split(None, 5)
                if len(parts) == 6 and inside(parts[5]):
                    raise RuntimeError("daemon package still has a live mapped reference")
        except FileNotFoundError:
            continue  # process exited during bounded read
        except PermissionError as error:
            raise RuntimeError("daemon package process custody is UNKNOWN") from error


def manifest(root: Path) -> dict:
    result = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if relative == "install.lock":
            continue  # the shared native lock must retain its own inode
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if path.is_symlink():
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root.resolve()):
                raise RuntimeError("package link escapes its payload tree")
            target = os.path.relpath(resolved, path.parent.resolve())
            result[relative] = ["link", target]
        elif path.is_dir():
            result[relative] = ["directory", mode]
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            result[relative] = ["file", mode, info.st_size, digest.hexdigest()]
        else:
            raise RuntimeError("package contains an unsupported file type")
    return result


def migrate_stopped(home: Path, durable: Path) -> None:
    """Called only AFTER the normal Remote Control stop, never to force a cycle.

    A mismatched shared release or unproven process custody retains the old
    directory. The same-user provisioning lock serializes migrations; the
    native install.lock is shared with the package updater.
    """
    old = home / "packages" / "app-server-daemon"
    if old.is_symlink() or not old.exists():
        prepare(home, durable)
        return
    if not home.is_absolute() or not durable.is_absolute() or old.parent.is_symlink():
        raise RuntimeError("migration paths must be absolute and card-specific")
    info = old.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError("existing package directory has unproven ownership")
    assert_quiescent(old)
    ancestor = durable
    while not ancestor.exists():
        ancestor = ancestor.parent
    if filesystem(ancestor.resolve()) in {"tmpfs", "ramfs"}:
        raise RuntimeError("daemon package destination is RAM-backed")
    if durable.is_symlink():
        raise RuntimeError("daemon package destination must be a real private directory")
    durable.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    parent_info = durable.parent.stat()
    if parent_info.st_uid != os.getuid() or stat.S_IMODE(parent_info.st_mode) != 0o700:
        raise RuntimeError("shared package parent must be user-owned mode0700")
    lock_path = durable.parent / ".daemon-package-provision.lock"
    if lock_path.exists() or lock_path.is_symlink():
        lock_info = lock_path.lstat()
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid():
            raise RuntimeError("provision lock custody is UNKNOWN")
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        expected = manifest(old)
        if not durable.exists():
            stage = Path(tempfile.mkdtemp(prefix=".daemon-package-", dir=durable.parent))
            try:
                shutil.copytree(old, stage, dirs_exist_ok=True, symlinks=True,
                                ignore=lambda directory, names: ["install.lock"] if Path(directory) == old else [])
                for relative, entry in expected.items():
                    if entry[0] == "link":
                        link = stage / relative
                        link.unlink()
                        link.symlink_to(entry[1])
                stage.chmod(0o700)
                if manifest(stage) != expected or manifest(old) != expected:
                    raise RuntimeError("package copy integrity is UNKNOWN")
                stage.rename(durable)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        destination = durable.stat()
        if destination.st_uid != os.getuid() or stat.S_IMODE(destination.st_mode) != 0o700:
            raise RuntimeError("shared package destination must be user-owned mode0700")
        native_lock = durable / "install.lock"
        if native_lock.exists() or native_lock.is_symlink():
            lock_info = native_lock.lstat()
            if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid():
                raise RuntimeError("shared native install lock must be a user-owned real file")
        with native_lock.open("a+b") as installer:
            fcntl.flock(installer, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if manifest(durable) != expected or manifest(old) != expected:
                raise RuntimeError("shared package differs; preserve existing card package")
            assert_quiescent(old)
            backup = Path(tempfile.mkdtemp(prefix=".stopped-daemon-", dir=old.parent))
            backup.rmdir()
            old.rename(backup)
            try:
                old.symlink_to(durable, target_is_directory=True)
            except OSError:
                backup.rename(old)
                raise
            # Recheck after the switch. A late reference retains the backup;
            # no unverified live payload is removed to reclaim capacity.
            assert_quiescent(backup)
            if manifest(backup) != expected or manifest(durable) != expected:
                raise RuntimeError("post-switch package custody is UNKNOWN; backup retained")
            shutil.rmtree(backup)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--migrate-stopped", action="store_true")
    parser.add_argument("--durable", required=True, type=Path)
    args = parser.parse_args()
    try:
        (migrate_stopped if args.migrate_stopped else prepare)(args.home, args.durable)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"daemon package provisioning refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
