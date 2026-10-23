"""The input box as a surface you can ASK and ACT on — aegis-c6hli.

WHY THIS EXISTS
Claude Code renders a suggestion ("ghost text") in the input box: something it
recommends you say, TAB-completable, drawn faint. It is byte-distinguishable
from typed text ONLY by a rendering attribute, and `tmux capture-pane -p` strips
exactly that attribute.

So a coordinator eyeballing a pane sees `❯ file the reconcile bead for ian` and
cannot tell a SUGGESTION from a line somebody typed into the agent and never
submitted. On 2026-08-01 one read the first as the second and ran the
stranded-input SOP on it: a coordinator turn and an interrupt into a working
agent, spent on a phantom. Both directions are live and neither is acceptable:

  FALSE POSITIVE  ghost read as stranded -> phantom stall, churn, interrupts.
  FALSE NEGATIVE  after enough phantoms a coordinator learns to dismiss "text in
                  the box" — and the next one is a REAL injection (aegis-apz9).

An SOP that fires constantly on a benign condition is how the SOP gets ignored.

WHAT THIS MODULE GUARANTEES
It NEVER submits. It cannot: every keystroke goes through Tmux.control, whose
allowlist has no Enter and no Tab. Tab is excluded as carefully as Enter — TAB
ACCEPTS THE SUGGESTION, so a "cleanup" path that typed Tab would inject the
suggestion into the agent's turn. That is the aegis-apz9 injection performed by
the tool built to prevent it.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from . import triage

# The coordinator-facing vocabulary. triage's constants are the internal ones and
# stay as they are (work_state and a corpus of tests speak them); these are what a
# human reads. Mapped in ONE place, below, so the two cannot drift.
EMPTY = "EMPTY"
TYPED = "TYPED"
GHOST = "GHOST"
UNKNOWN = "UNKNOWN"
ABSENT = "NO-BOX"
# A BLOCKING option-picker, not an input box at all. Found by running the live
# sweep rather than by reasoning: an agent sitting on a permission prompt
# reported TYPED "1. Yes", because the picker marks its SELECTED OPTION with the
# same ❯ glyph the input box uses. A coordinator reading that would run the
# stranded-input SOP on an agent whose actual problem is that it needs an
# ANSWER — the same false positive this bead exists to remove, one pane over.
#
# work_state never showed it because it checks `awaiting` BEFORE the input box;
# --show had no such check, so the bug was mine and new. Runtime chrome stays
# out of this module (triage is runtime-blind by construction): the caller
# passes the runtime's own verdict in, exactly as work_state takes `awaiting`.
PICKER = "PICKER"
TASK_LIST = "TASK-LIST"
BUSY = "BUSY"

_FROM_TRIAGE = {
    triage.INPUT_EMPTY: EMPTY,
    triage.INPUT_QUEUED: TYPED,
    triage.INPUT_PLACEHOLDER: GHOST,
    triage.INPUT_UNKNOWN: UNKNOWN,
    triage.INPUT_ABSENT: ABSENT,
}

# How long to wait for the TUI to repaint after an editing key, and how often to
# look. See _settle: the repaint is the whole difficulty of this module.
_SETTLE_S = 3.0
_POLL_S = 0.15


@dataclass
class Report:
    verdict: str
    evidence: str          # the raw prompt line the verdict was made on
    text: str              # what a human would see in the box
    changed: bool = True   # did the pane repaint when we expected it to?
    detail: str = ""


def _codex_box(screen: str) -> tuple[str, str, str] | None:
    """Read only the bounded composer immediately above Codex's model footer."""
    rows = screen.splitlines()
    while rows and not triage.strip_attrs(rows[-1]).strip():
        rows.pop()
    plain = [triage.strip_attrs(row) for row in rows]
    footers = [i for i in range(max(0, len(rows) - 8), len(rows))
               if re.match(r"\s*(?:GPT|gpt|codex)[\w.-]*(?:\s+\S+)?\s+·\s+(?:~|/)", plain[i])]
    if not footers:
        return None
    end = footers[-1]
    for start in range(end - 1, max(-1, end - 81), -1):
        if not plain[start].lstrip().startswith("›"):
            continue
        raw = "\n".join(rows[start:end]).rstrip()
        text = "\n".join(plain[start:end]).lstrip()[1:].strip()
        if not text or text == "Ask Codex to do anything":
            return EMPTY, raw, ""
        # Other suggestions need their actual dim attribute; typed runs win.
        if "\x1b" in raw:
            typed, ghost = triage._split_dim(raw[raw.index("›") + 1:])
            if not typed.strip() and ghost.strip():
                return GHOST, raw, text
        return TYPED, raw, text
    return None


def _codex_busy(screen: str) -> bool:
    rows = triage.strip_attrs(screen).splitlines()
    prompts = [i for i, row in enumerate(rows) if row.lstrip().startswith("›")]
    if not prompts:
        return True
    start = prompts[-1]
    return (any(re.match(r"\s*[•·]?\s*Working\b.*esc to interrupt", row, re.I)
                for row in rows[max(0, start - 8):start])
            or any("tab to queue message" in row.lower() for row in rows[start:]))


def _classify(screen: str) -> tuple[str, str, str]:
    from .harness import task_list_evidence
    evidence = task_list_evidence(screen)
    if evidence:
        return TASK_LIST, evidence, ""
    codex = _codex_box(screen)
    if codex is not None:
        return codex
    state = triage.input_state(screen)
    raw = triage.input_evidence(screen)
    plain = triage.strip_attrs(raw).strip()
    # Everything after the prompt glyph, as a human sees it.
    text = plain[1:].strip("\xa0 \t") if plain else ""
    return _FROM_TRIAGE.get(state, UNKNOWN), raw, text


def show(panes, pane: str, awaiting: bool = False) -> Report:
    """Classify the box, and hand back the bytes the verdict rests on.

    The evidence is not decoration. A verdict without it is precisely what got us
    here — the SOP was run on a confident reading of a capture that had thrown
    the deciding bit away, and nothing in the output could have contradicted it.
    """
    screen = panes.capture(pane, attrs=True)
    verdict, raw, text = _classify(screen)
    detail = ""
    if verdict == TASK_LIST:
        return Report(TASK_LIST, raw, text, detail=(
            "REFUSED: pane is on the task list; running task count unknown. "
            "Open the intended task, or use st inbox -d. Typing here starts "
            "a new parallel task."))
    if awaiting:
        return Report(PICKER, raw, text, detail=(
            "a BLOCKING option-picker is up — this pane needs an ANSWER, not a "
            "clear. The ❯ here marks the selected OPTION, not an input box."))
    if verdict == UNKNOWN:
        detail = ("the capture carries no escape sequences at all, so the dim "
                  "attribute was stripped before it got here — this is a refusal, "
                  "not a guess. Capture with attrs=True (tmux -e).")
    return Report(verdict, raw, text, detail=detail)


def _prompt_line(screen: str) -> str:
    return _classify(screen)[1]


def _settle(panes, pane: str, before: str) -> tuple[str, bool]:
    """Wait for the pane to actually REPAINT. Returns (screen, changed).

    THE REPAINT TRAP, and it cost real time before it was understood:
    `capture-pane` returns THE LAST PAINTED FRAME, not the input buffer. After
    sending C-u to a pane, every capture still showed the original text — the
    keys HAD landed, the TUI simply had not redrawn yet. A verifier that trusts
    that frame reports "clear failed" forever and escalates a stall that does not
    exist.

    So we do not read once and believe it. We poll until the prompt line CHANGES,
    and if it has not changed by half the budget we send C-a — cursor-to-start, a
    pure no-op on an empty buffer — purely to give the TUI a state change to
    re-render on. C-a is chosen because it cannot alter or accept anything; the
    obvious alternatives are not safe here (Right accepts the autosuggestion in
    readline-alikes, and Escape means something else in this module).

    `changed=False` is returned honestly rather than being reported as failure.
    "The pane never repainted" and "the clear did not work" are different facts,
    and collapsing them is the same class of bug as everything else in this file.
    """
    deadline = time.monotonic() + _SETTLE_S
    nudged = False
    screen = panes.capture(pane, attrs=True)
    while time.monotonic() < deadline:
        if _prompt_line(screen) != before:
            return screen, True
        if not nudged and time.monotonic() > deadline - _SETTLE_S / 2:
            try:
                panes.control(pane, "C-a")
            except Exception:
                pass
            nudged = True
        time.sleep(_POLL_S)
        screen = panes.capture(pane, attrs=True)
    return screen, _prompt_line(screen) != before


def clear(panes, pane: str, awaiting: bool = False) -> Report:
    """Clear TYPED text. REFUSES on a ghost-only box, and says why.

    Refusing is not pedantry. There is nothing to clear in a suggestion — the
    buffer is already empty — so "clearing" one would appear to work, teach the
    operator that suggestions are stalls, and manufacture exactly the phantom
    workload this bead was filed about.
    """
    screen = panes.capture(pane, attrs=True)
    verdict, raw, text = _classify(screen)

    if verdict == TASK_LIST:
        return Report(TASK_LIST, raw, text, detail=(
            "REFUSED: pane is on the task list; running task count unknown. "
            "Open the intended task, or use st inbox -d. Typing here starts "
            "a new parallel task."))
    if awaiting:
        return Report(PICKER, raw, text, detail=(
            "REFUSED: a BLOCKING option-picker is up. Clearing would send C-u "
            "into a prompt that is waiting on a decision, and the ❯ on screen "
            "is the selected OPTION, not typed input. Answer it, or attach."))
    if _codex_box(screen) is not None and _codex_busy(screen):
        return Report(BUSY, raw, text, detail="REFUSED: Codex is busy; no editing keys sent.")
    if verdict == GHOST:
        return Report(verdict, raw, text, detail=(
            "REFUSED: this is a SUGGESTION, not typed input — the buffer is "
            "already empty and there is nothing to clear. Use --dismiss to make "
            "it go away. (Nothing is stalled: an agent showing a suggestion has "
            "an empty box.)"))
    if verdict == EMPTY:
        return Report(verdict, raw, text, detail="nothing to clear — the box is empty.")
    if verdict == ABSENT:
        return Report(verdict, raw, text, detail=(
            "REFUSED: no input box on this pane. Not a runtime prompt, or the "
            "pane is showing something else entirely."))
    if verdict == UNKNOWN:
        return Report(verdict, raw, text, detail=(
            "REFUSED: cannot tell typed text from a suggestion on this capture, "
            "so clearing would be acting blind on a pane that may be perfectly "
            "healthy. This is the refusal the whole module exists to make."))

    if _codex_box(screen) is not None:
        # C-u kills one logical line; BSpace then removes its preceding newline.
        # No Enter, Tab, Escape or interrupt is sent, even on a busy refusal.
        for _ in range(81):
            if _codex_busy(screen):
                return Report(BUSY, raw, text, detail="REFUSED: Codex is busy; no further editing keys sent.")
            before = _prompt_line(screen)
            previous_text = text
            for key in ("C-e", "C-u", "BSpace"):
                panes.control(pane, key)
            screen, changed = _settle(panes, pane, before)
            after = _codex_box(screen)
            if after is None:
                return Report(UNKNOWN, "", "", detail="REFUSED: Codex composer disappeared during clear.")
            verdict, raw, text = after
            if verdict in (EMPTY, GHOST):
                return Report(verdict, raw, text, detail="cleared — Codex empty placeholder verified.")
            if not changed:
                return Report(verdict, raw, text, changed=False,
                              detail="No repaint after clear; buffer state UNKNOWN.")
            if _codex_busy(screen):
                return Report(BUSY, raw, text, detail="REFUSED: Codex became busy; no further editing keys sent.")
            if len(text) >= len(previous_text) or not previous_text.startswith(text):
                return Report(TYPED, raw, text,
                              detail="REFUSED: composer changed unexpectedly; preserving remaining text.")
        return Report(TYPED, raw, text, detail="REFUSED: Codex clear exceeded bounded line budget.")

    before = _prompt_line(screen)
    panes.control(pane, "C-e")   # to end of line first: C-u kills to the LEFT of
    panes.control(pane, "C-u")   # the cursor, so a mid-line cursor would leave a tail
    screen, changed = _settle(panes, pane, before)
    after_verdict, after_raw, after_text = _classify(screen)

    if not changed:
        return Report(after_verdict, after_raw, after_text, changed=False, detail=(
            "the keys were sent but the pane never repainted within "
            f"{_SETTLE_S:g}s, so this frame proves NOTHING about the buffer. Do "
            "not read this as failure — the clear may well have landed. Look "
            "again, or attach."))
    if after_verdict in (EMPTY, GHOST):
        detail = "cleared — box is empty."
        if after_verdict == GHOST:
            detail += " The runtime repainted its suggestion over the empty buffer."
        return Report(after_verdict, after_raw, after_text, detail=detail)
    return Report(after_verdict, after_raw, after_text, detail=(
        f"clear did not empty the box: it now reads {after_verdict}. "
        "The pane DID repaint, so this is a real result, not a stale frame."))


def dismiss(panes, pane: str) -> Report:
    """Send Escape to make a suggestion go away.

    Only useful against a GHOST box, but permitted on any — Escape is harmless
    and an operator who wants the box visually clean should not have to argue
    with the tool about it.
    """
    screen = panes.capture(pane, attrs=True)
    before = _prompt_line(screen)
    verdict, raw, text = _classify(screen)
    if verdict == TASK_LIST:
        return Report(TASK_LIST, raw, text, detail=(
            "REFUSED: pane is on the task list; open the intended task first."))
    panes.control(pane, "Escape")
    screen, changed = _settle(panes, pane, before)
    verdict, raw, text = _classify(screen)
    if not changed:
        return Report(verdict, raw, text, changed=False,
                      detail=f"Escape sent; no repaint within {_SETTLE_S:g}s, so this "
                             "frame is not evidence either way.")
    return Report(verdict, raw, text, detail="Escape sent.")
