"""Role settings that drift from the code, and live agents still on old ones.

MEASURED (aegis-za4f.20, sattler 2026-11-28 03:35Z): #764 added the operator
capture hook to the administrator's UserPromptSubmit and was installed, yet
nothing was captured. administrator.settings.json had last been emitted at
07:46Z, before #764, and nothing re-emits role settings when st changes. Then
the hand re-emit did not reach the live pane either, because Claude Code reads
--settings only at launch. So there are two separate faults: the FILE is stale
against the code, and the PROCESS is stale against the file.

`st fleet tend` runs this sweep every pass:
  1. A role file whose bytes differ from what the current code renders is
     re-emitted, unless the re-render would DROP a hook command. A drop is
     what a hand-added hook in an st-owned event looks like. Removing it
     silently on a timer is worse than leaving it stale, so it is held, and
     the line names `st fleet roles set` (which warns and drops).
  2. A live agent whose launch stamp no longer matches its file
     (launched.verdict == STALE) gets an automatic REPLACE cycle request
     (no_in_place: an in-place clear keeps the process and so the old
     settings). tend serves auto requests only at an idle pane, never mid-turn.
  3. The administrator is never cycled by this. It gets a notice
     (`admin_notices`, shown on its anchor) instead.
"""
from __future__ import annotations

from pathlib import Path

ADMIN_ROLE = "administrator"
SETTINGS_STALE = "SETTINGS STALE"


def _per_agent(path: Path) -> bool:
    return path.name.startswith("agent-") or path.parent.name.startswith("agent-")


def reemit_drifted(root, render, write, log=lambda text: None) -> tuple[list[Path], list[Path]]:
    """(re-emitted, held) role files.

    render(harness, role) -> (path, existing_text, rendered_text, dropped)
    where dropped is the hook commands the re-render would remove.
    write(path, text) writes atomically. Per-agent files are rendered at that
    agent's launch, so they are not touched here (same rule as hooks reassert).
    """
    from . import hook_bundles as hb
    files, _unresolved = hb.emitted_role_files(root)
    done: list[Path] = []
    held: list[Path] = []
    for harness, role, path in files:
        if _per_agent(path):
            continue
        try:
            p, existing, rendered, dropped = render(harness, role)
        except Exception as exc:  # noqa: BLE001 — one bad role must not stop the sweep
            log(f"settings-drift: could not render {harness}/{role} "
                f"({type(exc).__name__}: {exc}); {path} left as is, drift UNKNOWN")
            continue
        if rendered == existing:
            continue
        if dropped:
            held.append(p)
            log(f"settings-drift: {p} differs from the code but a re-render would "
                f"DROP {len(dropped)} hook command(s) ({sorted(dropped)[:3]}); held. "
                f"Run `st fleet roles set` to re-emit and accept the drop")
            continue
        write(p, rendered)
        done.append(p)
        log(f"settings-drift: re-emitted {p} (it differed from what this st renders)")
    return done, held


def stale_live(agents, launches, is_live) -> list:
    """Live cards whose loaded settings are older than their file, in name order."""
    from .launched import STALE
    out = []
    for card in agents:
        if getattr(card, "retired", False) or not is_live(card):
            continue
        if launches.verdict(card.name) == STALE:
            out.append(card)
    return sorted(out, key=lambda c: c.name)


def request_cycles(stale, requests, checkpoint, log=lambda text: None) -> list[str]:
    """File an idle REPLACE cycle for each stale non-administrator. Returns names
    requested or upgraded now.

    A pending request is KEPT (its checkpoint is the requester's) but made a
    relaunch: an in-place clear keeps the process and so the old settings.
    The pending check comes BEFORE the checkpoint, because a checkpoint
    comments on the agent's work item and a busy agent is seen on every tend
    pass; checkpointing first posted the same comment each pass for nothing.
    """
    asked = []
    for card in stale:
        if card.role == ADMIN_ROLE:
            log(f"settings-drift: {card.name} (administrator) is {SETTINGS_STALE}; "
                f"notice only, never cycled automatically")
            continue
        upgraded = requests.require_replace(card.name)
        if upgraded is None:
            try:
                snap = checkpoint(card)
            except Exception as exc:  # noqa: BLE001 — no checkpoint, no cycle
                log(f"settings-drift: {card.name} is {SETTINGS_STALE} but the automatic "
                    f"checkpoint failed ({type(exc).__name__}: {exc}); no cycle requested")
                continue
            if requests.request(card.name, snap["text"], snap.get("item", ""),
                                snap.get("nodes", []), no_in_place=True, auto=True,
                                settings_stale=True, only_if_absent=True):
                asked.append(card.name)
                log(f"settings-drift: {card.name} is {SETTINGS_STALE}; replace cycle "
                    f"requested for its next idle pass")
                continue
            # Another writer filed one between the check and ours: upgrade that.
            upgraded = requests.require_replace(card.name)
        if upgraded:
            asked.append(card.name)
            log(f"settings-drift: {card.name} is {SETTINGS_STALE}; its pending cycle "
                f"request now relaunches instead of clearing in place")
    return asked


def admin_notices(agents, launches) -> list[str]:
    """One line per agent st launched on settings that have changed since.

    Read from the launch stamps (a stopped agent's stamp is forgotten), so this
    needs no pane probe and is safe on the anchor's hot path.
    """
    from .launched import STALE
    lines = []
    for card in sorted(agents, key=lambda c: c.name):
        if getattr(card, "retired", False) or launches.verdict(card.name) != STALE:
            continue
        if card.role == ADMIN_ROLE:
            lines.append(f"{SETTINGS_STALE}: {card.name} runs on settings older than its "
                         f"file; hooks added since are not loaded. Cycle at your next "
                         f"idle: `st agent cycle {card.name} --no-in-place -r '...'`")
        else:
            lines.append(f"{SETTINGS_STALE}: {card.name} runs on older settings; "
                         f"a replacement cycle will load the current file")
    return lines
