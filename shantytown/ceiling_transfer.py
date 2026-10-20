"""Moving ceiling-held work to a claude agent with headroom (aegis-qbl).

Stiwi, 2026-10-14: *"Don't wait on usage ceilings move to claude this should be
a built in st capability"*. Measured the same morning: kelly held aegis-z2k, on
the P0 9lb path, "at the existing session ceiling", and harding handed three
items to other crew by hand when she reached hers. Work that waits for a
ceiling to reset is work nobody is doing.

## What is a ceiling here

Two signals st already reads, and only those two:

* the st SESSION ceiling (`session_budget.at_ceiling`: hours, items or risk
  actions this session), which stops the agent's haul until a new session; and
* a usage LIMIT on the agent's model that tend could not clear: the pane shows
  the "usage limit reached" banner and no fallback model is declared, so tend
  reports it and waits for the reset (`tend.LIMITED` with `acted=False`). An
  agent tend DID fail over to its fallback model is running again and is not a
  source.

## Where the work goes

To a LIVE, non-retired claude agent that is not itself at a ceiling, limited,
held (agent hold or gaming quiet time) or the source, and whose plate count is
under the cap (Stiwi 2026-10-14, "Max like 10"). Among those, the one with the
most room, then by name, so the choice is reproducible.

## How it moves

This module only DECIDES; `apply` performs each move through injected effects,
and the CLI injects the existing dispatcher (`st go` with `--reassign` and a
note). That is deliberate: the dispatcher already refuses a busy pane, sends
then verifies on the pane before writing, reads the tracker write back, and
refuses closed, blocked and gated items. A second, private assignment path
would have to re-earn every one of those refusals.

A move that fails is reported and left for the next pass; it is never retried
inside a pass, and a dispatch that may have landed is never re-sent. Once
triage refuses a receiver, remaining moves to that receiver are reported as
skipped for this pass. Other receivers continue; the next pass checks afresh.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Plate cap per crew member (Stiwi 2026-10-14). A target at the cap gets nothing.
PLATE_CAP = 10
TARGET_HARNESS = "claude"


@dataclass(frozen=True)
class Holder:
    """An agent at a ceiling, and the plate item it holds."""

    agent: str
    item: str
    #: "session ceiling" or "usage limit".
    why: str
    #: The measured evidence, quoted into the item comment.
    evidence: str


@dataclass(frozen=True)
class Candidate:
    """A possible receiver. `unavailable` names why it cannot take work ("" = it can)."""

    agent: str
    harness: str
    assigned: int
    unavailable: str = ""


@dataclass(frozen=True)
class Move:
    item: str
    frm: str
    to: str
    why: str
    evidence: str

    def note(self) -> str:
        """The caveat that rides WITH the dispatch, on the receiver's pane."""
        return (f"moved from {self.frm} at its {self.why} ({self.evidence}); "
                f"read {self.frm}'s notes and checkpoint on the item before acting")

    def comment(self) -> str:
        """The one item comment recording the move."""
        return (f"st ceiling-transfer (aegis-qbl): moved {self.item} from {self.frm} "
                f"to {self.to}. Why: {self.frm} is at its {self.why}: {self.evidence}. "
                f"{self.frm}'s notes and checkpoint stay on this item; {self.to} "
                f"continues from them.")


@dataclass(frozen=True)
class Stay:
    """A held item that is NOT moved this pass, and why."""

    item: str
    frm: str
    why: str


@dataclass(frozen=True)
class Outcome:
    move: Move
    moved: bool
    detail: str = ""
    commented: bool = False
    disposition: str = "unknown"


@dataclass
class Plan:
    moves: list[Move] = field(default_factory=list)
    stays: list[Stay] = field(default_factory=list)


def receiver_budget(limits, spend, ceiling) -> str:
    """Why a receiver's session budget does NOT show headroom ("" when it does).

    Reads the whole `session_budget.gate` tuple, never `at_ceiling` alone.
    `at_ceiling` is fail-open by design (an agent must never be kept from its OWN
    work because a budget could not be read), so its None means "not withheld",
    not "has room". Moving someone ELSE's work onto an agent needs the positive
    fact, so an unknown budget refuses the move (wu review of ST248). The
    ordinary haul's fail-open policy is untouched; this only gates transfers.

    The order matters: gate()'s own error path returns INACTIVE limits with
    signal_lost=True, so signal_lost must be read before the inactive-policy
    case or a failed read would pass as "no budget declared".
    """
    if ceiling is not None:
        return "at its own ceiling"
    if spend.signal_lost:
        return "session budget UNKNOWN (signal lost)"
    if not limits.active:
        # No [session_budget] limit is declared: a known policy, not a failed read.
        return ""
    if not spend.session:
        return "session budget UNKNOWN (no attributable current session)"
    return ""


def plan(holders, candidates, *, cap: int = PLATE_CAP,
         harness: str = TARGET_HARNESS) -> Plan:
    """Decide the moves. Pure: no reads, no writes."""
    out = Plan()
    holding = {h.agent for h in holders}
    room = {}
    for c in candidates:
        if (c.harness == harness and not c.unavailable and c.agent not in holding
                and c.assigned < cap):
            room[c.agent] = cap - c.assigned
    for h in sorted(holders, key=lambda h: (h.agent, h.item)):
        if not room:
            out.stays.append(Stay(h.item, h.agent,
                                  f"no live {harness} agent has headroom under the "
                                  f"plate cap of {cap}"))
            continue
        to = min(room, key=lambda name: (-room[name], name))
        out.moves.append(Move(h.item, h.agent, to, h.why, h.evidence))
        room[to] -= 1
        if room[to] <= 0:
            del room[to]
    return out


def apply(moves, *, dispatch, comment, emit, log) -> list[Outcome]:
    """Perform each move once. `dispatch(item, to, note)` raises to refuse.

    The comment and the event follow a SUCCESSFUL dispatch only. A comment
    failure after a delivered move is logged loudly and never undoes the move:
    the work has moved, and only the record is missing.
    """
    from .dispatch import DispatchedButUntracked, TriageRefused
    results = []
    refused = {}
    for m in moves:
        if m.to in refused:
            detail = f"receiver refused earlier this pass: {refused[m.to]}"
            log(f"ceiling-transfer: {m.item} stays with {m.frm}; {m.to} skipped ({detail})")
            results.append(Outcome(m, False, detail, disposition="not_attempted"))
            continue
        try:
            dispatch(m.item, m.to, m.note())
        except DispatchedButUntracked as exc:
            # The send WAS confirmed on the receiver's pane; only the tracker
            # write is unproven. Saying "stays with" here would be false, and a
            # resend would deliver the work twice.
            detail = f"{type(exc).__name__}: {exc}"
            log(f"ceiling-transfer: {m.item} was DELIVERED to {m.to} but the tracker "
                f"write is unproven; do not resend, repair the assignee ({detail})")
            results.append(Outcome(m, False, detail, disposition="delivered_untracked"))
            continue
        except Exception as exc:  # noqa: BLE001 - every refusal is reported, none retried
            detail = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, TriageRefused):
                refused[m.to] = detail
            log(f"ceiling-transfer: {m.item} stays with {m.frm}; moving it to "
                f"{m.to} was refused or unproven ({detail})")
            results.append(Outcome(m, False, detail, disposition=(
                "refused" if isinstance(exc, TriageRefused) else "unproven")))
            continue
        commented = True
        try:
            comment(m.item, m.comment())
        except Exception as exc:  # noqa: BLE001
            commented = False
            log(f"ceiling-transfer: {m.item} MOVED to {m.to} but its item comment "
                f"was not recorded ({type(exc).__name__}); add it by hand")
        try:
            emit({"kind": "ceiling-transfer", "item": m.item, "from": m.frm,
                  "to": m.to, "why": m.why, "evidence": m.evidence})
        except Exception as exc:  # noqa: BLE001
            log(f"ceiling-transfer: event for {m.item} not recorded ({type(exc).__name__})")
        log(f"ceiling-transfer: moved {m.item} {m.frm} -> {m.to} ({m.why})")
        results.append(Outcome(m, True, commented=commented, disposition="confirmed"))
    return results
