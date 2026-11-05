"""Keep a tmux server out of the short-lived user service launching it.

Pane scopes do not move the server. A detached tmux client can return while its
server remains in a oneshot's cgroup, where normal service cleanup kills it.
A transient user scope preserves the caller's environment and outlives that
client while the server remains. Never fall back after a refused scope launch.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import uuid


def user_service(cgroups: str, uid: int) -> str | None:
    """Read the unified (or legacy systemd) hierarchy, not a CPU controller.

    The user manager itself and login/pane scopes need no escape. Only a service
    below this user's manager owns the service-cleanup hazard addressed here.
    """
    records = []
    for line in cgroups.splitlines():
        fields = line.split(":", 2)
        if len(fields) != 3 or not fields[2].startswith("/"):
            raise ValueError("unreadable launcher cgroup record")
        if fields[0] == "0" and fields[1] == "":
            records.insert(0, fields[2])
        elif "name=systemd" in fields[1].split(","):
            records.append(fields[2])
    if not cgroups.strip():
        raise ValueError("empty launcher cgroup membership")
    for path in records:
        parts = path.split("/")
        manager = f"user@{uid}.service"
        if manager not in parts:
            continue
        descendants = parts[parts.index(manager) + 1:]
        units = [p for p in descendants if p.endswith((".service", ".scope"))]
        if units and units[-1].endswith(".service"):
            return units[-1]
    return None


def launch_argv(command: list[str]) -> list[str]:
    """Isolate service-origin launches; scope failures remain launch failures."""
    if sys.platform != "linux":
        return command
    try:
        service = user_service(Path("/proc/self/cgroup").read_text(), os.getuid())
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeError("cannot determine tmux launcher's service cgroup") from exc
    if service is None:
        return command
    # A unique unit also permits a new client when an older scope still holds
    # surviving processes. Do not stop, migrate or replace an existing server.
    return ["systemd-run", "--user", "--scope", "--quiet", "--collect",
            "--expand-environment=no", f"--unit=st-tmux-{uuid.uuid4().hex}",
            "--", *command]
