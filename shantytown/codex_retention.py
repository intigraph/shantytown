"""Opt-in retention for legacy role-owned Codex release payloads.

Arming: agent-invoked; no launch hook, automatic deletion or cron is installed.
Only packages/standalone/releases is in scope. State and sessions are not.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time
import uuid

ROLES = ("worker", "lead", "keeper", "administrator")
RELEASE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-([a-z0-9_-]+)\Z")
MIN_AGE = 86400


class Refused(RuntimeError):
    pass


def owned(path: Path, *, directory=False):
    info = path.lstat()
    if info.st_uid != os.getuid() or (directory and not stat.S_ISDIR(info.st_mode)):
        raise Refused(f"unowned or non-directory payload: {path}")
    return info


def release_snapshot(path: Path):
    """Metadata identity, allocated bytes and age; never follows external links."""
    owned(path, directory=True)
    records, allocated, newest = [], 0, 0
    for parent, directories, files in os.walk(path, followlinks=False):
        for name in [".", *directories, *files]:
            item = Path(parent) if name == "." else Path(parent) / name
            info = owned(item)
            if stat.S_ISLNK(info.st_mode):
                target = item.resolve(strict=True)
                if not target.is_relative_to(path) or not target.is_file():
                    raise Refused(f"external or non-file payload link: {item}")
            elif not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise Refused(f"special payload file: {item}")
            records.append([str(item.relative_to(path)), info.st_dev, info.st_ino,
                            info.st_mode, info.st_size, info.st_mtime_ns,
                            info.st_ctime_ns, os.readlink(item) if item.is_symlink() else None])
            if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                allocated += info.st_blocks * 512
            newest = max(newest, info.st_mtime)
    meta = json.loads((path / "codex-package.json").read_text())
    match = RELEASE.fullmatch(path.name)
    if (not match or meta.get("layoutVersion") != 1
            or meta.get("variant") != "codex"
            or meta.get("version") != ".".join(match.groups()[:3])
            or meta.get("target") != match.group(4)
            or meta.get("entrypoint") != "bin/codex"
            or not (path / "bin/codex").is_file()):
        raise Refused(f"unknown package layout: {path}")
    identity = hashlib.sha256(json.dumps(sorted(records), separators=(",", ":")).encode()).hexdigest()
    return {"identity": identity, "bytes": allocated, "newest": newest}


def process_paths(proc: Path = Path("/proc")):
    """Same-UID readers; an unreadable live process is UNKNOWN, never absent.

    Inspect only executable/mappings/open-file paths, not environment, command
    arguments or file contents. Other-UID payload use is outside this contract.
    """
    if not proc.is_dir():
        raise Refused("process filesystem unavailable")
    paths, saw_self = set(), False
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            saw_self = saw_self or process.name == str(os.getpid())
            paths.add(os.readlink(process / "exe").removesuffix(" (deleted)"))
            for line in (process / "maps").read_text().splitlines():
                columns = line.split(maxsplit=5)
                if len(columns) == 6 and columns[5].startswith("/"):
                    paths.add(columns[5].removesuffix(" (deleted)"))
            for fd in (process / "fd").iterdir():
                try:
                    value = os.readlink(fd).removesuffix(" (deleted)")
                    if value.startswith("/"):
                        paths.add(value)
                except FileNotFoundError:
                    continue  # this particular descriptor closed
        except FileNotFoundError:
            if process.exists():
                raise Refused("live process inspection incomplete") from None
        except OSError:
            raise Refused("live process inspection unavailable") from None
    if not saw_self:
        raise Refused("process inspection lacks its own positive control")
    return paths


def referenced(path: Path, readers):
    return any(value == str(path) or value.startswith(str(path) + "/") for value in readers)


def inventory(home: Path, keep_previous: int, readers, now: float):
    if type(keep_previous) is not int or not 0 <= keep_previous <= 20:
        raise Refused("keep-previous must be an integer from 0 through 20")
    standalone = home / "packages/standalone"
    releases = standalone / "releases"
    for path in (home, home / "packages", standalone, releases):
        owned(path, directory=True)
    current = standalone / "current"
    owned(current)
    if not current.is_symlink():
        raise Refused("current must be an explicit release symlink")
    selected = current.resolve(strict=True)
    if selected.parent != releases:
        raise Refused("current escapes the release directory")
    rows = {}
    for path in releases.iterdir():
        if not RELEASE.fullmatch(path.name):
            raise Refused("unknown entry in releases")
        rows[path.name] = release_snapshot(path)
    if selected.name not in rows or not rows:
        raise Refused("current package is missing")
    versions = sorted(rows, key=lambda name: tuple(int(x) for x in RELEASE.fullmatch(name).groups()[:3]))
    platforms = {RELEASE.fullmatch(name).group(4) for name in versions}
    if len(platforms) != 1:
        raise Refused("mixed package platforms")
    # The launch resolver may repair current to latest, so protect both.
    anchors = {selected.name, versions[-1]}
    anchors.update(name for name in versions if referenced(releases / name, readers))
    retained = set(anchors)
    for anchor in anchors:
        index = versions.index(anchor)
        retained.update(versions[max(0, index - keep_previous):index])
    for name in versions:
        if now - rows[name]["newest"] < MIN_AGE:
            retained.add(name)
    return {"home": str(home), "keep_previous": keep_previous,
            "current": os.readlink(current), "releases": rows,
            "retained": sorted(retained), "remove": sorted(set(rows) - retained)}


def prune(home: Path, keep_previous=2, *, expected=None, readers=None,
          now=time.time):
    """Plan by default. Execution needs an exact saved plan and rechecks custody."""
    home = home.absolute()
    readers = process_paths if readers is None else readers
    # Resolve and reject aliases rather than operate through a role symlink.
    if home.resolve(strict=True) != home:
        raise Refused("home must be a canonical physical directory")
    standalone = home / "packages/standalone"
    owned(standalone, directory=True)
    if not shutil.rmtree.avoids_symlink_attacks:
        raise Refused("safe directory removal unavailable")
    # Lock the directory itself: no lock file in credential/session state.
    fd = os.open(standalone, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = inventory(home, keep_previous, readers(), now())
        if expected is None:
            return {"plan": plan, "removed": [], "freed_bytes": 0}
        if plan != expected:
            raise Refused("saved plan no longer matches current inventory or readers")
        removed, freed = [], 0
        for name in plan["remove"]:
            fresh = inventory(home, keep_previous, readers(), now())
            remaining = {key: value for key, value in plan["releases"].items() if key not in removed}
            if (fresh["current"] != plan["current"] or fresh["releases"] != remaining
                    or name not in fresh["remove"]):
                raise Refused("package, current or live-reader state changed; partial result retained")
            path = standalone / "releases" / name
            detached = path.with_name(".retiring-" + uuid.uuid4().hex)
            os.rename(path, detached)
            print("DETACHED " + json.dumps({"release": name, "temporary": detached.name}),
                  file=sys.stderr, flush=True)
            try:
                # A pre-rename open executable/map/fd now names this directory.
                if referenced(detached, readers()):
                    raise Refused("payload gained a live reader before deletion")
                shutil.rmtree(detached)
            except BaseException:
                if detached.exists() and not path.exists():
                    os.rename(detached, path)
                    print("RESTORED_NAME " + name + "; removal may have been partial",
                          file=sys.stderr, flush=True)
                raise
            removed.append(name)
            freed += plan["releases"][name]["bytes"]
            print("REMOVED " + json.dumps({"release": name,
                                         "estimated_freed_bytes": plan["releases"][name]["bytes"]}),
                  file=sys.stderr, flush=True)
        return {"plan": plan, "removed": removed, "freed_bytes": freed}
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="deployment root containing settings/codex")
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument("--keep-previous", type=int, default=2)
    parser.add_argument("--execute-plan", type=Path, help="execute only this saved plan; otherwise read-only")
    args = parser.parse_args(argv)
    home = args.root.absolute() / "settings/codex" / args.role
    try:
        expected = None
        if args.execute_plan:
            expected = json.loads(args.execute_plan.read_text())["plan"]
            if not isinstance(expected, dict):
                raise Refused("saved execution plan is not an object")
        result = prune(home, args.keep_previous, expected=expected)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
