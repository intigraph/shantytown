"""Opt-in, mount-required storage for future Codex sessions; never migrate history."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import stat
import sys

@dataclass(frozen=True)
class Storage:
    root: Path
    mount: Path
    device: tuple[int, int]
    minimum_free: int

    def argv(self) -> list[str]:
        return ["--root", str(self.root), "--mount", str(self.mount),
                "--device", f"{self.device[0]}:{self.device[1]}",
                "--minimum-free", str(self.minimum_free)]

    def command(self, *, home: Path | None = None) -> str:
        args = [sys.executable, "-m", "shantytown.session_storage", *self.argv()]
        if home is not None:
            args += ["--home", str(home)]
        return shlex.join(args)


def configured(root=None) -> Storage | None:
    from .deployment import deployment_default
    names = ("SHANTY_CODEX_SESSIONS_ROOT", "SHANTY_CODEX_SESSIONS_MOUNT",
             "SHANTY_CODEX_SESSIONS_DEVICE", "SHANTY_CODEX_SESSIONS_MIN_FREE")
    values = [deployment_default(root, name) for name in names]
    if all(value is None for value in values):
        return None
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError("session storage requires root, mount, device and minimum free bytes")
    destination, mount, device, minimum = values
    return parse(destination, mount, device, minimum)


def parse(root: str, mount: str, device: str, minimum: str) -> Storage:
    destination, mounted = Path(root), Path(mount)
    if (not destination.is_absolute() or not mounted.is_absolute()
            or ".." in destination.parts or ".." in mounted.parts
            or destination == mounted or mounted not in destination.parents):
        raise ValueError("session root must be an absolute strict descendant of its mount")
    parts = device.split(":")
    if len(parts) != 2 or not all(part.isdecimal() for part in parts):
        raise ValueError("session device must be decimal major:minor")
    if not minimum.isdecimal() or int(minimum) <= 0:
        raise ValueError("session minimum free bytes must be positive")
    return Storage(destination, mounted, (int(parts[0]), int(parts[1])), int(minimum))


def validate_observation(device, expected, root_device, kind, available, minimum):
    if device != expected or device == root_device:
        raise RuntimeError("session destination is on the wrong device or root filesystem")
    if kind in {"tmpfs", "ramfs"}:
        raise RuntimeError("session destination is RAM-backed")
    if available < minimum:
        raise RuntimeError("session destination has insufficient available space")


@contextmanager
def admitted(storage: Storage):
    """Pin the actual mount; relative writes cannot fall back beneath an unmount."""
    if not sys.platform.startswith("linux"):
        raise RuntimeError("mount-required session storage is supported on Linux only")
    # codex_packages uses Linux custody primitives; keep legacy imports portable.
    from .codex_packages import filesystem
    if (storage.mount.resolve(strict=True) != storage.mount
            or not storage.mount.is_mount()):
        raise RuntimeError("required session mount is absent or noncanonical")
    fd = os.open(storage.mount, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        root = Path("/").stat().st_dev
        space = os.fstatvfs(fd)
        validate_observation(
            (os.major(info.st_dev), os.minor(info.st_dev)), storage.device,
            (os.major(root), os.minor(root)), filesystem(storage.mount),
            space.f_bavail * space.f_frsize, storage.minimum_free,
        )
        yield fd
    finally:
        os.close(fd)


def prepare(storage: Storage, home: Path) -> None:
    """Only fresh or already matching homes; existing histories require a cold cutover."""
    link = home / "sessions"
    with admitted(storage) as mount_fd:
        if not home.is_absolute() or home.resolve(strict=True) != home:
            raise RuntimeError("session home must be an existing canonical directory")
        if link.is_symlink():
            if os.readlink(link) != str(storage.root):
                raise RuntimeError("existing session link requires verified stopped migration")
        elif link.exists():
            raise RuntimeError("existing session directory requires verified stopped migration")
        parent = os.dup(mount_fd)
        try:
            for component in storage.root.relative_to(storage.mount).parts:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=parent)
                os.close(parent)
                parent = child
                info = os.fstat(parent)
                if (info.st_dev != os.fstat(mount_fd).st_dev or info.st_uid != os.getuid()
                        or stat.S_IMODE(info.st_mode) != 0o700):
                    raise RuntimeError("session directories must be same-device user-owned mode0700")
            os.fsync(parent)
            available = os.fstatvfs(parent)
            if available.f_bavail * available.f_frsize < storage.minimum_free:
                raise RuntimeError("session headroom changed during preparation")
            if (not storage.mount.is_mount()
                    or storage.mount.stat().st_dev != os.fstat(mount_fd).st_dev):
                raise RuntimeError("session mount changed during preparation")
            if link.is_symlink():
                if os.readlink(link) != str(storage.root):
                    raise RuntimeError("session link changed during preparation")
            else:
                # Creation refuses a raced-in entry instead of replacing its history.
                link.symlink_to(storage.root, target_is_directory=True)
        finally:
            os.close(parent)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "mount", "device", "minimum-free"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--home", type=Path)
    args = parser.parse_args(argv)
    try:
        storage = parse(args.root, args.mount, args.device, args.minimum_free)
        if args.home is None:
            with admitted(storage):
                pass
        else:
            prepare(storage, args.home)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"REFUSED session storage: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
