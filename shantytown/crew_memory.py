"""Read the existing workspace's Claude memory for a Codex startup.

No second memory store, provisioning write, account-profile scan or tracker
dependency. Notes are historical context; they do not supply new authority.
"""
from __future__ import annotations

import hashlib
import codecs
from dataclasses import replace
import os
from pathlib import Path
import re
import stat

MAX_BYTES = 32768
MAX_LINES = 200
BANNER = "[st crew memory — shared workspace context]"


def render(card, *, memory_home: Path | None = None) -> str:
    """Return a bounded prefix from THIS Codex card's existing project memory."""
    if card.harness != "codex" or not card.workspace:
        return ""
    workspace = Path(card.workspace).expanduser()
    if not workspace.is_absolute():
        return f"{BANNER} runtime workspace is not absolute; memory coverage UNKNOWN."
    workspace = workspace.resolve()
    key = re.sub(r"[^a-zA-Z0-9]", "-", str(workspace))
    projects = (memory_home or Path.home() / ".claude") / "projects"
    project = projects / key
    memory = project / "memory"
    source = memory / "MEMORY.md"
    try:
        # Do not let another workspace or an arbitrary file masquerade as this
        # card's memory. The projects root itself may be operator-managed.
        if project.is_symlink() or memory.is_symlink() or source.is_symlink():
            raise ValueError("symlink in project memory")
        fd = os.open(source, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("memory is not a regular file")
            raw = handle.read(MAX_BYTES + 1)
            after = os.fstat(handle.fileno())
            if (info.st_mtime_ns, info.st_size) != (after.st_mtime_ns, after.st_size):
                raise ValueError("memory changed during read")
        # An incomplete UTF-8 codepoint at the byte cap is omitted, not replaced.
        prefix = codecs.getincrementaldecoder("utf-8")().decode(
            raw[:MAX_BYTES], final=len(raw) <= MAX_BYTES)
        lines = prefix.splitlines(keepends=True)
        text = "".join(lines[:MAX_LINES])
        truncated = len(raw) > MAX_BYTES or len(lines) > MAX_LINES
        if not text.strip():
            return ""
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        coverage = ("TRUNCATED: bounded prefix; later directives may be omitted. "
                    "Read the original full index before relying on these notes"
                    if truncated else "complete file")
        return (f"{BANNER}\nSource: {source}\n"
                f"Loaded text SHA256: {digest}; {coverage}.\n"
                "Historical notes only: verify current facts and authority. "
                "Maintain this same source file; do not create a harness-specific copy.\n\n"
                f"{text}")
    except FileNotFoundError:
        return ""
    except (OSError, ValueError, UnicodeError):
        return f"{BANNER} existing project memory unreadable; coverage UNKNOWN."


def for_agent(root: str, agent: str) -> str:
    """Resolve the runtime card locally; missing cards never select cwd memory."""
    try:
        from .files import FilesRegistry
        from .accounts import selected
        from .config import load
        card = FilesRegistry(Path(root) / "crew").get(agent)
        cfg = load(root)
        harness = card.harness or cfg.harness_by_role.get(card.role) or cfg.harness_default or "claude"
        if harness != "codex":
            return ""
        card = replace(card, harness=harness)
        account = selected(card, cfg)
        memory_home = None
        if account is not None:
            # Never borrow another subscription's projects or fall back from a
            # named account to the legacy profile. No credentials are opened.
            from .account_auth import profile
            memory_home = profile(root, account)
        return render(card, memory_home=memory_home)
    except Exception:  # startup context must not prevent an anchor from loading
        return f"{BANNER} runtime identity/account unreadable; memory coverage UNKNOWN."
