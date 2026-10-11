"""Prepare one instruction body for all harnesses, without touching identity files."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from . import config_source


@dataclass(frozen=True)
class Plan:
    updates: dict[Path, str]
    comparisons: dict[str, dict]


def prepare(workspace, card, cfg):
    if cfg.source_document is None:
        return Plan({}, {})
    mode = cfg.env.get("SHANTY_INSTRUCTIONS_MODE", "compare")
    if mode not in ("compare", "apply"):
        raise ValueError("SHANTY_INSTRUCTIONS_MODE must be compare or apply")
    ws = Path(workspace).resolve()
    if (ws / "AGENTS.override.md").exists():
        raise ValueError("instruction override shadows the canonical body")
    text = config_source.render(cfg.source_document, card.name, card.role,
                                card.harness or "claude")
    if not text:
        raise ValueError("selected instruction fragments render an empty body")
    after = text.encode("utf-8")
    updates, comparisons = {}, {}
    for name in ("CLAUDE.md", "AGENTS.md"):
        target = (ws / name).resolve()
        if not target.is_relative_to(ws):
            raise ValueError("instruction destination leaves the agent workspace")
        before = target.read_bytes() if target.exists() else b""
        comparisons[name] = {
            "before_sha256": hashlib.sha256(before).hexdigest(),
            "after_sha256": hashlib.sha256(after).hexdigest(),
            "before_bytes": len(before), "after_bytes": len(after),
            "equal": before == after,
        }
        if mode == "apply" and before != after:
            updates[target] = text
    return Plan(updates, comparisons)
