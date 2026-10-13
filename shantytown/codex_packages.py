"""Keep per-card daemon payloads off Linux runtime tmpfs without live deletion."""
from __future__ import annotations

import argparse
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
    """Create a fresh private disk destination; refuse existing payload custody."""
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--durable", required=True, type=Path)
    args = parser.parse_args()
    try:
        prepare(args.home, args.durable)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"daemon package provisioning refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
