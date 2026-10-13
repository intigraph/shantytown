"""Keep daemon payloads in one disk package outside Linux runtime tmpfs without live deletion."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
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
    """Strict custody remains required for any future destructive operation."""
    scan_custody(root, bounded=False)


def quarantine_custody(root: Path) -> dict:
    """Identity-only coverage permits retention, never certifies deletion."""
    return scan_custody(root, bounded=True)


def scan_custody(root: Path, *, bounded: bool) -> dict:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("stopped package custody cannot be verified on this platform")
    resolved = str(root.resolve())
    def inside(value):
        value = value.removesuffix(" (deleted)")
        return value == resolved or value.startswith(resolved + os.sep)
    processes = sorted(Path("/proc").iterdir(), key=lambda p: p.name != str(os.getpid()))
    if len(processes) > 8192:
        raise RuntimeError("process custody exceeds its bounded inventory")
    deadline = time.monotonic() + 15
    protected, established = [], 0
    for proc in processes:
        if time.monotonic() > deadline:
            raise RuntimeError("process custody exceeded its deadline")
        if not proc.name.isdecimal():
            continue
        try:
            status = (proc / "status").read_text()
            uid_line = next((line for line in status.splitlines() if line.startswith("Uid:")), None)
            uids = uid_line.split()[1:] if uid_line else []
            if len(uids) != 4 or not all(value.isdecimal() for value in uids):
                raise RuntimeError("process UID custody is UNKNOWN")
            if os.getuid() not in [int(value) for value in uids]:
                continue
            denied = []
            try:
                executable = os.readlink(proc / "exe")
                if inside(executable):
                    raise RuntimeError("daemon package still has a live executable reference")
            except FileNotFoundError:
                pass  # absent leader exe does not skip descriptors/maps
            except PermissionError:
                denied.append("exe")
            try:
                for descriptor in (proc / "fd").iterdir():
                    try:
                        if inside(os.readlink(descriptor)):
                            raise RuntimeError("daemon package still has an open descriptor")
                    except FileNotFoundError:
                        continue
                    except PermissionError:
                        denied.append("fd-link")
            except PermissionError:
                denied.append("fd")
            try:
                for line in (proc / "maps").read_text().splitlines():
                    parts = line.split(None, 5)
                    if len(parts) == 6 and inside(parts[5]):
                        raise RuntimeError("daemon package still has a live mapped reference")
            except PermissionError:
                denied.append("maps")
            if denied:
                if not bounded:
                    raise RuntimeError("daemon package process custody is UNKNOWN")
                # Read every remaining identity field; never print command arguments.
                identity_before = (proc / "stat").read_text()
                with (proc / "cmdline").open("rb") as stream:
                    raw = stream.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise RuntimeError("protected process identity exceeds its bound")
                args = raw.split(b"\0")
                argv0 = os.fsdecode(args[0])
                comm = (proc / "comm").read_text().strip()
                fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
                start = fields[19]
                before_fields = identity_before.rsplit(")", 1)[1].split()
                if before_fields[19] != start or (proc / "status").read_text() != status:
                    raise RuntimeError("protected process identity changed during custody scan")
                if not comm or not start.isdecimal():
                    raise RuntimeError("protected process identity is UNKNOWN")
                if "codex" in (comm + " " + argv0).lower() or any(inside(os.fsdecode(arg)) for arg in args):
                    raise RuntimeError("protected process is a plausible payload consumer")
                protected.append({"pid": int(proc.name), "comm": comm,
                                  "start_ticks": int(start), "denied": sorted(set(denied)),
                                  "coverage": "BOUNDED"})
            else:
                established += 1
        except FileNotFoundError as error:
            if proc.exists():
                raise RuntimeError("existing process metadata custody is UNKNOWN") from error
        except (PermissionError, IndexError) as error:
            raise RuntimeError("daemon package process custody is UNKNOWN") from error
    return {"root": str(root), "coverage": "BOUNDED" if protected else "ESTABLISHED",
            "readable_processes": established, "protected": protected,
            "deletion": "HOLD"}


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

    A mismatched shared release or unidentified process retains the old
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
    quarantine_custody(old)
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
            quarantine_custody(old)
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
            # The original tree stays on the same filesystem for a complete
            # natural-card-cycle soak. No successful scan authorizes deletion.
            report = quarantine_custody(backup)
            receipt = {**report, "quarantine": str(backup), "home": str(home),
                       "durable": str(durable), "observed_unix": time.time(),
                       "rollback": "at stopped boundary: unlink expected package symlink, rename quarantine back",
                       "soak": "HOLD: require one full natural cycle of every live Codex card"}
            # Receipt creation must not overwrite a prior migration's evidence.
            receipt_path = backup.with_name(backup.name + ".json")
            with os.fdopen(os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
                json.dump(receipt, stream, sort_keys=True)
                stream.write("\n")
            print(json.dumps(receipt), file=sys.stderr)

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
