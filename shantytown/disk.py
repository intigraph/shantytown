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


def watched_path(policy, root) -> Path:
    """The filesystem worktrees land on: the explicit disk_path, else the
    mounted worktree storage root, else the st root."""
    explicit = getattr(policy, "disk_path", "") or ""
    if explicit:
        return Path(explicit)
    try:
        from . import worktree_storage
        storage = worktree_storage.configured_root()
    except Exception:  # noqa: BLE001 — a bad storage file is not a disk reading
        storage = None
    return Path(storage) if storage else Path(root)


def read(policy, root, *, usage=None) -> Reading:
    floor = int(getattr(policy, "disk_floor_gb", 0) or 0)
    path = watched_path(policy, root)
    if floor <= 0:
        return Reading(OFF, str(path), 0)
    try:
        u = (usage or shutil.disk_usage)(path)
    except OSError as error:
        return Reading(LOST, str(path), floor, error=type(error).__name__)
    free, total = u.free / GB, u.total / GB
    return Reading(LOW if free < floor else OK, str(path), floor, free, total)
