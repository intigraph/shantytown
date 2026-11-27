"""Disk space as a governed resource (aegis-xa6w).

2026-11-27 /srv/fleet held 55G free of 2.2T (98%) while worktrees drained up to
-44 GB/h, and the only brake was a human pausing the ephemeral pool by hand.
Every job provisions a worktree on that filesystem, so free space is a capacity
the spawn gate must read, exactly like an account's usage budget.

`[ephemeral] disk_floor_gb` sets the floor; 0 is off. Below it a fresh spawn
QUEUES with a named reason (never refused, no work lost) and the drain launches
nothing; tend kicks the drain once space is back, so nobody has to pause or
resume the pool.

BLIND IS HELD, NOT ADMITTED. A configured floor whose filesystem cannot be read
(`lost`) holds launches the same as `low`: admitting on a reading we do not have
is the governor fail-safe running backwards. It is loud on `st crew --governor`.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

GB = 1024 ** 3

OFF, OK, LOW, LOST = "off", "ok", "low", "lost"


@dataclass(frozen=True)
class Reading:
    state: str
    path: str
    floor_gb: int
    free_gb: float | None = None
    total_gb: float | None = None
    error: str = ""

    @property
    def holds(self) -> bool:
        return self.state in (LOW, LOST)

    def line(self) -> str:
        """The `st crew --governor` line: status word first, like every lane."""
        if self.state == OFF:
            return "disk off"
        if self.state == LOST:
            return (f"disk lost floor {self.floor_gb}G on {self.path} ({self.error}): "
                    "ephemeral spawns queue")
        tail = ": ephemeral spawns queue" if self.state == LOW else ""
        return (f"disk {self.state} {self.free_gb:.0f}G free/floor {self.floor_gb}G"
                f"/{self.total_gb:.0f}G on {self.path}{tail}")

    def refusal(self) -> str:
        """The named queue reason, or "" when space admits a launch."""
        if self.state == LOW:
            return (f"disk below floor: {self.free_gb:.0f}G free on {self.path}, floor "
                    f"{self.floor_gb}G; queued, launches once space is back")
        if self.state == LOST:
            return (f"disk free space unreadable on {self.path} ({self.error}); floor "
                    f"{self.floor_gb}G is held; queued")
        return ""

    def wire(self) -> dict:
        return dict(state=self.state, path=self.path, floor_gb=self.floor_gb,
                    free_gb=None if self.free_gb is None else round(self.free_gb, 1),
                    total_gb=None if self.total_gb is None else round(self.total_gb, 1))


def watched_path(policy, root) -> tuple[Path, str]:
    """The filesystem to watch and, when it cannot be named, why.

    The explicit disk_path, else the mounted worktree storage root, else the st
    root. With no storage configured, worktrees land beside their checkout
    (`<repo>-wt`), which may be a different mount from the st root: such a host
    must set disk_path, and the governor line names the path it reads so a wrong
    one is visible. A storage file that is present but invalid is NOT "no
    storage": configured_root refuses to fall back on explicit invalid choices,
    and reading the st root's filesystem instead would report a healthy number
    for the wrong disk. That is a blind reading, and BLIND IS HELD."""
    explicit = getattr(policy, "disk_path", "") or ""
    if explicit:
        return Path(explicit), ""
    from . import worktree_storage
    try:
        storage = worktree_storage.configured_root()
    except worktree_storage.StorageError as error:
        return Path(root), f"worktree storage: {error}"
    return (Path(storage) if storage else Path(root)), ""


def read(policy, root, *, usage=None) -> Reading:
    floor = int(getattr(policy, "disk_floor_gb", 0) or 0)
    path, blind = watched_path(policy, root)
    if floor <= 0:
        return Reading(OFF, str(path), 0)
    if blind:
        return Reading(LOST, str(path), floor, error=blind)
    try:
        u = (usage or shutil.disk_usage)(path)
    except OSError as error:
        return Reading(LOST, str(path), floor, error=type(error).__name__)
    free, total = u.free / GB, u.total / GB
    return Reading(LOW if free < floor else OK, str(path), floor, free, total)


# --- reclaim regenerable build output from ended jobs (aegis-xa6w) -------------
# 2026-11-27 sattler reclaimed 30G by hand: ended ephemeral jobs whose worktree
# teardown KEPT the tree (it holds work) still carried cargo target/ dirs of up
# to 8G each. The commits and edits are the work; a git-ignored build cache is
# not, and rebuilding it is what a resumed job would do anyway.
BUILD_CACHES = ("target",)


def purge_build_caches(dest, *, git) -> list[str]:
    """Remove git-ignored build-cache dirs at the top of a worktree.

    Only a real directory (never a symlink) that git itself says is ignored and
    that carries cargo's mark, so a tracked `target/` source directory, another
    tool's ignored output or a link out of the tree is untouched.
    Returns the names removed."""
    import shutil as _shutil
    dest = Path(dest)
    removed = []
    for name in BUILD_CACHES:
        cache = dest / name
        if cache.is_symlink() or not cache.is_dir():
            continue
        ignored = git("-C", str(dest), "check-ignore", "-q", name)
        if ignored.returncode != 0:
            continue
        tracked = git("-C", str(dest), "ls-files", "--", name)
        if tracked.returncode != 0 or tracked.stdout.strip():
            continue
        # An ignored target/ that is not cargo's is someone's output, not
        # debris: the same proof teardown demands (#765, aegis-g68w.32).
        if not ((cache / "CACHEDIR.TAG").is_file() or (dest / "Cargo.toml").is_file()):
            continue
        _shutil.rmtree(cache, ignore_errors=True)
        if not cache.exists():
            removed.append(name)
    return removed
