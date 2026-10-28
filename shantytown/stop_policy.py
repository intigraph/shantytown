"""stop_policy — ONE stop decision. `python -m shantytown.stop_policy --root <dir>`.

Built to docs/stop-policy-spec.md. An agent's Stop hook was a CHAIN of independent
commands, each able to return {"decision":"block"} on its own and none of them
aware of the others. Measured consequences: a documented config knob (hibernate)
that was inert because a second hook blocked the same stop; the same panes scraped
up to three times in one turn boundary; and two policies whose overlap nobody had
had to reconcile because nothing forced them into one answer.

THE RANKS. Ordered, first match wins. This list IS the specification — a reader
must be able to answer "why did my coordinator not stop?" from it alone.

  0  route + persist MY OWN stop event upward      (side effect, never blocks)
  1  a pending event is URGENT (governance / rose)  -> BLOCK: deliver
  1a explicit admin routine-wake budget (opt-in) -> ALLOW: batch ordinary wakes
  2  RULE ZERO: free feedable AND dispatchable      -> BLOCK: dispatch
  2a P0 PLATE: ready P0 nobody works AND capacity    -> BLOCK once per state
  3  hibernate declines                             -> ALLOW, loudly
  4  a DELIVERABLE pending event                    -> BLOCK: deliver
  5  idle because a GOVERNOR TIER holds the queue   -> ALLOW, loudly
  6  otherwise                                      -> ALLOW

RANK 5 IS AN ALLOW THAT REFUSES TO BE SILENT (aegis-diasw). Under an engaged
usage tier, an idle fleet with a full ready queue is the CORRECT state — and it
is observationally identical to a feeder that has broken. A coordinator that
cannot tell them apart assumes the second, because that is the one it can act on;
and the action available to it is to re-grade a P2 to P1 until the queue clears
the floor. That is priority inflation manufactured by two mechanisms disagreeing,
and it defeats the throttle at exactly the moment the throttle is working.

The fix is to remove the PUSH, not the escape hatch: `st go`'s refusal still
offers the bump, because bd history records priority per revision so an inflation
is auditable after the fact (ruled by Stiwi, who withdrew the decision that would
have reworded it). What this rank removes is the blocking hook demanding an action
the governor forbids — nobody is herded toward the hatch, so a bump becomes a
judgement someone made rather than one the mechanism extracted.

RANK 2 ABOVE RANK 3 IS THE WHOLE FIX. Hibernate can now only fire in a state where
quiet is correct — nothing urgent, nothing to hand out — and when Rule Zero
overrides it, the output says so by name instead of the knob appearing broken.

RANK 2a IS RULE ZERO FOR THE ADMINISTRATOR'S OWN PLATE (aegis-c01c.1). Rule
Zero only saw (free crew) x (unassigned ready work). With the one crew member
busy, ten unstarted P0s — on the administrator's own plate or unassigned — were
invisible, and the administrator stopped with "much work to do". Rank 2a blocks
when a READY P0 nobody is working on meets CAPACITY to start it: a free crew
member or a free ephemeral slot for unassigned work, a free self slot
(`[fleet] admin_self_slots` minus the administrator's own in_progress items) for
its own. It yields to stood-down and over-capacity exactly as rank 2 does, and
it blocks ONCE per unchanged (plate, capacity) state: a second stop over the
same state ALLOWS, loudly, so a deliberate "not now" cannot become a loop.

RANK 3 ABOVE RANK 4 IS THE FEATURE, not a gap. A hibernating administrator sleeps
through ORDINARY worker reports: with nothing dispatchable, a "kelly stopped" is
informational and there is no decision to make. It is safe for exactly one reason —
rank 3 ALLOWS without consuming anything, so the next wake sees the whole batch.

FAIL OPEN, ranks 1-5. Any error — tmux, bd, registry, a config typo — allows the
stop. A hook that wedges an agent on a transient hiccup is worse than the stall it
prevents. Rank 0 is the exception: persisting my own stop event is survival, not a
decision, so a failure there is reported rather than swallowed into a clean-looking
allow.

NOT AN `st` SUBCOMMAND, for the same reason stop_event is not: this is hook
plumbing, and the command surface is pinned.
"""
from __future__ import annotations

from .query_identity import declared_command

import json
import os
import sys
from dataclasses import dataclass, field

from . import config
from . import feed_check as feed_mod
from . import stop_event
from . import triage
from .events import FilesEvents
from .files import FilesRegistry
from .hibernate import WakeLog
from .runtime import ClaudeRuntime
from .tier import is_governance
from .tmux import Tmux

# Which rank decided. Emitted on stderr, so "went quiet" and "is wedged" are
# distinguishable without reading this file.
BY_STOOD_DOWN = "stood-down"
BY_URGENT = "urgent"
BY_RULE_ZERO = "rule-zero"
BY_P0_PLATE = "p0-plate"
BY_P0_UNCHANGED = "p0-plate-unchanged"
BY_HIBERNATE = "hibernating"
BY_EVENTS = "events"
BY_THROTTLED = "governor-throttled"
BY_ADMIN_BUDGET = "admin-wake-budget"
BY_NOTHING = "nothing-to-do"
BY_ERROR = "fail-open"


@dataclass(frozen=True)
class P0Item:
    """One READY P0 nobody is working on: open, unblocked, not deferred, not an
    epic/message/decision/parked item, and either unassigned or on the
    administrator's own plate. `owner` is "" for unassigned."""
    id: str
    title: str = ""
    owner: str = ""


@dataclass(frozen=True)
class Capacity:
    """What could START a P0 right now. Three sources, one shape, so the
    ephemeral agents of aegis-c01c.2 plug in as a number rather than a new rank.

    free_crew       — Rule Zero's free feedable workers (idle, unhauled)
    ephemeral_slots — free `st agent spawn --ephemeral` slots (0 until that lands)
    self_slots      — the administrator's own free slots: `[fleet]
                      admin_self_slots` minus its in_progress items. In-flight
                      in-process subagent work is counted HERE, as occupancy.

    Unassigned work needs a crew member or an ephemeral slot; the
    administrator's own items need a self slot. A coordinator is not told to
    execute unassigned work itself — it is told to hand it out.
    """
    free_crew: tuple = ()
    ephemeral_slots: int = 0
    self_slots: int = 0

    def can_start(self, item: "P0Item") -> bool:
        if item.owner:
            return self.self_slots > 0
        return bool(self.free_crew) or self.ephemeral_slots > 0

    def describe(self) -> str:
        parts = []
        if self.free_crew:
            parts.append(f"free crew: {', '.join(sorted(self.free_crew))}")
        if self.ephemeral_slots:
            parts.append(f"{self.ephemeral_slots} free ephemeral slot(s)")
        if self.self_slots:
            parts.append(f"{self.self_slots} free slot(s) of your own")
        return "; ".join(parts) or "none"


@dataclass(frozen=True)
class Verdict:
    block: bool
    reason: str          # reaches the MODEL when blocking (the block protocol)
    by: str              # which rank decided; stderr only


@dataclass
class Inputs:
    """Everything the ranks read, gathered ONCE.

    The single sweep is both properties at once: the ranks cannot disagree about
    who is busy (they are looking at the same instant), and one turn boundary
    costs one scrape instead of three.
    """
    me: str
    role: str
    pending: list = field(default_factory=list)      # NOT consumed — a read
    free_feedable: list = field(default_factory=list)
    dispatchable: int = 0
    # Ready, unassigned, claimable — and REFUSED BY THE GOVERNOR's priority floor
    # (aegis-diasw). Not folded into `dispatchable`: the whole defect was that
    # "throttle holding" and "feeder broken" were the same observation, and one
    # number cannot carry both. `throttled_why` is the governor's own sentence.
    throttled: int = 0
    throttled_why: str = ""
    hibernate: "config.Hibernate | None" = None
    minutes_quiet: float | None = None
    fleet: "config.Fleet | None" = None
    load_per_core: float | None = None      # None = could not measure
    # Senders observed mid-flight at THIS sweep. Empty = nothing known busy, so
    # everything is deliverable — the same fail-open `_drain` uses when it has no
    # pane backend: refusing to act on a check we did not run would be worse than
    # the bug. See `deliverable`.
    busy_senders: set = field(default_factory=set)
    # RANK 2a (aegis-c01c.1). `p0_plate` is ORDERED (seeds priority, then rank),
    # so the block reason names the top items. `p0_last` is the state rank 2a
    # last blocked or declined on, from the ledger; `p0_held` counts unassigned
    # P0s the governor's floor refused (rank 5 names them).
    p0_plate: list = field(default_factory=list)
    capacity: Capacity = field(default_factory=Capacity)
    p0_last: str | None = None
    p0_held: int = 0
    throttled_ids: set[str] = field(default_factory=set)
    p0_held_ids: set[str] = field(default_factory=set)
    admin_wake_mode: str = "off"
    admin_usage_pct: float | None = None
    admin_wake_elapsed: float | None = None

    @property
    def deliverable(self) -> list:
        """Pending events that would ACTUALLY be handed over on this stop.

        Ordinary stops from a busy sender are obsolete at any age. Urgent
        governance and risen events still deliver immediately. gather consumes
        the obsolete snapshot before deciding, so an ALLOW does not leave
        old events queued to wake an administrator later.
        """
        out = []
        for e in self.pending:
            if (is_governance(e.reason) or e.rose
                    or getattr(e, "frm", None) not in self.busy_senders):
                out.append(e)
        return out

    @property
    def p0_startable(self) -> list:
        """The P0 plate items some free capacity could start, in plate order."""
        if self.role != "administrator":
            return []
        return [i for i in self.p0_plate if self.capacity.can_start(i)]

    @property
    def urgent(self) -> list:
        """Events that must never be slept on. A governance alert's content is
        'an agent is working RIGHT NOW outside the tracker'; a risen event means
        the tier already failed once by the time the admin sees it."""
        return [e for e in self.pending if is_governance(e.reason) or e.rose]


def decide(inp: Inputs) -> Verdict:
    """THE decision. Pure: it takes measurements, never makes them.

    Separated from the gathering so the ordering — the part that has to be
    argued — is testable without a tmux, a clock, a registry or a bd.
    """
    if inp.urgent:
        kinds = ", ".join(sorted({e.reason or "escalation" for e in inp.urgent}))
        return Verdict(True, f"{len(inp.urgent)} event(s) that must not wait "
                             f"({kinds}).", BY_URGENT)

    # Explicit admin cadence outranks ordinary dispatch, unlike idle hibernate.
    # Urgent events above always bypass it. ALLOW consumes no pending events.
    from .admin_wake_budget import remaining
    wait = remaining(inp.admin_usage_pct, inp.admin_wake_elapsed)
    if inp.role == "administrator" and inp.admin_wake_mode == "enforce" and wait:
        return Verdict(False, f"routine admin wake deferred for {wait:.0f}s; "
                       f"{len(inp.pending)} event(s) remain PENDING. "
                       "Urgent/operator work bypasses this cadence; ongoing "
                       "turn spend is not bounded.", BY_ADMIN_BUDGET)

    # RULE ZERO'S TWO PRECONDITIONS (GitHub #29, #23). Both make the gate
    # satisfiable by RESTRAINT, which it was not: it could only ever demand more
    # dispatch, so a deliberate quiet period was indistinguishable from neglect.
    stood_down = bool(inp.fleet and inp.fleet.stood_down)
    over_capacity = False
    cap = inp.fleet.max_load_per_core if inp.fleet else 0.0
    if cap and inp.load_per_core is not None:
        over_capacity = inp.load_per_core > cap

    if inp.free_feedable and inp.dispatchable and stood_down:
        # The operator has DECLARED quiet. Rule Zero yields, and says so — a gate
        # that goes silent is indistinguishable from a gate that is broken.
        return Verdict(False,
                       f"the fleet is STOOD DOWN ({len(inp.free_feedable)} free "
                       f"worker(s) and {inp.dispatchable} ready item(s) left "
                       f"alone). Clear `[fleet] stood_down` to resume dispatch.",
                       BY_STOOD_DOWN)

    if inp.free_feedable and inp.dispatchable and over_capacity:
        return Verdict(False,
                       f"host load {inp.load_per_core:.1f}/core is over the "
                       f"{cap:.1f} ceiling — NOT demanding more dispatch onto a "
                       f"saturated box. {inp.dispatchable} item(s) wait.",
                       BY_STOOD_DOWN)

    if inp.free_feedable and inp.dispatchable:
        # RULE ZERO (aegis-hfta), and it OVERRIDES hibernate — but says so, which
        # is the difference between a policy and a knob that looks broken.
        note = ""
        if inp.hibernate is not None and inp.hibernate.enabled:
            note = (" Hibernate is enabled and was OVERRIDDEN: there is work to "
                    "hand out.")
        return Verdict(True,
                       f"{len(inp.free_feedable)} free feedable worker(s) "
                       f"({', '.join(sorted(inp.free_feedable))}) and "
                       f"{inp.dispatchable} dispatchable item(s). Dispatch, or "
                       f"say why not.{note}", BY_RULE_ZERO)

    startable = inp.p0_startable
    if startable:
        # RANK 2a. Same two restraint preconditions as Rule Zero, same words.
        if stood_down:
            return Verdict(False,
                           f"the fleet is STOOD DOWN ({len(startable)} ready P0 "
                           f"item(s) with capacity left alone). Clear `[fleet] "
                           f"stood_down` to resume.", BY_STOOD_DOWN)
        if over_capacity:
            return Verdict(False,
                           f"host load {inp.load_per_core:.1f}/core is over the "
                           f"{cap:.1f} ceiling — NOT demanding P0 starts on a "
                           f"saturated box. {len(startable)} P0 item(s) wait.",
                           BY_STOOD_DOWN)
    if startable and not _p0_unchanged(inp):
        top, more = _top(startable)
        note = ""
        if inp.hibernate is not None and inp.hibernate.enabled:
            note = (" Hibernate is enabled and was OVERRIDDEN: there is P0 work "
                    "to start.")
        return Verdict(True,
                       f"{len(startable)} ready P0 item(s) nobody is working on "
                       f"and capacity to start them ({inp.capacity.describe()}). "
                       f"Top by priority+rank: {top}{more}. Start them — hand "
                       f"out, spawn, or take your own — or re-rank/defer and "
                       f"say why. Blocks once per unchanged plate.{note}",
                       BY_P0_PLATE)

    # NOTHING PENDING IS NOT A HIBERNATION. It is the ordinary idle stop (rank 5),
    # which allows anyway. Claiming rank 3 here would report holding a backlog back
    # when there was no backlog, and an operator reading that goes looking for
    # events that do not exist.
    if inp.pending and inp.hibernate is not None and inp.hibernate.enabled:
        if not _batch_is_stale(inp):
            left = ""
            if inp.hibernate.max_quiet_minutes and inp.minutes_quiet is not None:
                remaining = inp.hibernate.max_quiet_minutes - inp.minutes_quiet
                left = f", or {remaining:.0f} min of quiet remaining"
            # "nothing dispatchable" is TRUE but incomplete when a tier is the
            # reason (aegis-diasw): an operator reading it goes looking for an
            # empty queue and finds a full one. Name the throttle here too.
            why = ""
            if inp.throttled:
                why = (f" ({inp.throttled} ready item(s) held by the usage "
                       f"governor's priority floor — idle is correct)")
            return Verdict(False,
                           f"nothing dispatchable{why}, nothing urgent. "
                           f"{len(inp.pending)} event(s) left PENDING, unconsumed. "
                           f"Next wake: a tend push, an inbox, a dispatch{left}.",
                           BY_HIBERNATE)

    if inp.deliverable:
        held = len(inp.pending) - len(inp.deliverable)
        # Name the held-back remainder IN the block line. Its absence is what
        # sent a coordinator to the events directory hunting a stuck-delivery bug
        # that was disclosed design all along (aegis-d1qko).
        note = (f" ({held} more held back — sender(s) still mid-flight)"
                if held else "")
        return Verdict(True,
                       f"{len(inp.deliverable)} pending event(s) to deliver."
                       f"{note}",
                       BY_EVENTS)

    # RANK 2a, SECOND HALF: an UNCHANGED plate. NO LOOP — the administrator was
    # already told about exactly this plate and capacity and stopped anyway;
    # that is a decision, and repeating the block would only make it again at a
    # token cost. It falls THROUGH rather than allowing at rank 2a, so hibernate
    # and event delivery below still behave exactly as without a plate; only
    # the final allows name what waits.
    unchanged = ""
    if startable:
        top, more = _top(startable)
        unchanged = (f"P0 plate UNCHANGED since the last block "
                     f"({len(startable)} ready P0 item(s): {top}{more}) — not "
                     f"blocking twice for the same state; a change to the "
                     f"plate or capacity re-arms it.")

    # RANK 5. Nothing to dispatch — and the governor is WHY. Said out loud, on an
    # ALLOW, because silence here is what trains a coordinator to go hunting for
    # a way to make work dispatchable. Deliberately AFTER the event ranks: a
    # throttled queue is no reason to sit on someone's undelivered report.
    idle = len(inp.free_feedable) + inp.capacity.ephemeral_slots
    held = inp.throttled + inp.p0_held - len(inp.throttled_ids & inp.p0_held_ids)
    if idle and held and not inp.dispatchable:
        return Verdict(False,
                       f"the usage governor is holding the queue: "
                       f"{idle} idle worker(s)/slot(s) and "
                       f"{held} ready item(s), 0 clearing the priority "
                       f"floor. IDLE IS CORRECT — the throttle is holding, not "
                       f"the feeder. Nothing here needs doing. "
                       f"{inp.throttled_why} {unchanged}".strip(),
                       BY_THROTTLED)
    if unchanged:
        return Verdict(False, unchanged, BY_P0_UNCHANGED)
    return Verdict(False, "", BY_NOTHING)


def _top(items) -> tuple[str, str]:
    top = ", ".join(_name(i) for i in items[:3])
    return top, (f" (+{len(items) - 3} more)" if len(items) > 3 else "")


def _p0_unchanged(inp: Inputs) -> bool:
    return inp.p0_last is not None and p0_state(inp) == inp.p0_last


def _name(item: P0Item) -> str:
    title = item.title if len(item.title) <= 60 else item.title[:57] + "..."
    return f"{item.id} ({title})" if title else item.id


def p0_state(inp: Inputs) -> str:
    """The (startable plate, capacity) fingerprint rank 2a refuses to block on
    twice. Order-insensitive in the plate; capacity by its three numbers and the
    free crew's names only when unassigned work can use them. Unrelated
    capacity churn must not re-arm a block over the administrator's own P0s."""
    ids = ",".join(sorted(i.id for i in inp.p0_startable))
    c = inp.capacity
    unassigned = any(not item.owner for item in inp.p0_startable)
    own = any(item.owner for item in inp.p0_startable)
    crew = c.free_crew if unassigned else ()
    return (f"{ids}|crew={','.join(sorted(crew))}"
            f"|eph={c.ephemeral_slots if unassigned else 0}"
            f"|self={c.self_slots if own else 0}")


def p0_ledger_update(inp: Inputs, verdict: Verdict) -> str | None:
    """What the rank-2a ledger should hold after this verdict, or None to leave
    it alone. Pure, so the no-loop property is testable without a disk.

    - rank 2a blocked: the state it judged.
    - a rank ABOVE 2a decided first (urgent, wake budget, Rule Zero, stood-down,
      fail-open): untouched — 2a never looked, so it must not be marked seen.
    - the plate is startable and UNCHANGED (whatever lower rank then decided):
      kept — this is the no-loop property.
    - otherwise 2a found nothing startable, so clear ("") — a plate that
      empties and refills is a new state and blocks again.
    """
    if inp.role != "administrator":
        return None
    if verdict.by == BY_P0_PLATE:
        return p0_state(inp)
    if verdict.by in (BY_URGENT, BY_ADMIN_BUDGET, BY_RULE_ZERO, BY_STOOD_DOWN,
                      BY_ERROR):
        return None
    if inp.p0_startable and _p0_unchanged(inp):
        return inp.p0_last
    return ""


class P0Ledger:
    """`<root>/stop-policy/<agent>.p0.json`: the state rank 2a last judged. A
    missing or unreadable ledger reads as None, i.e. "never judged", so the
    worst case of a lost ledger is one extra block, never a silent one."""

    def __init__(self, root):
        from pathlib import Path
        self._dir = Path(root) / "stop-policy"

    def _path(self, me: str):
        return self._dir / f"{me}.p0.json"

    def last(self, me: str) -> str | None:
        try:
            value = json.loads(self._path(me).read_text()).get("state")
        except (OSError, ValueError, AttributeError):
            return None
        return value if isinstance(value, str) else None

    def record(self, me: str, state: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path(me).with_suffix(".tmp")
        tmp.write_text(json.dumps({"state": state}))
        os.replace(tmp, self._path(me))


def _batch_is_stale(inp: Inputs) -> bool:
    """Has the pending batch gone unread longer than the operator allows?

    max_quiet_minutes is NOT a schedule to wake on — it is a bound on how long a
    pending batch may sit while nothing pushes. 0 disables it, which is a
    legitimate choice: `st fleet tend` pushes, and a push is a wake with a REASON, which
    beats a timer every time.
    """
    cap = inp.hibernate.max_quiet_minutes if inp.hibernate else 0
    if not cap or not inp.pending:
        return False
    if inp.minutes_quiet is None:
        return True          # never woken -> read the batch once, start the clock
    return inp.minutes_quiet >= cap


# --- gathering --------------------------------------------------------------

def gather(root, me: str, *, reg=None, panes=None, runtime=None,
           events=None, wake_log=None, now=None, p0_reader=None,
           p0_ledger=None) -> Inputs:
    """One sweep. Every dependency injectable so a test drives the ranks without
    tmux or bd."""
    import time
    reg = reg if reg is not None else FilesRegistry(root / "crew")
    panes = panes if panes is not None else Tmux()
    runtime = runtime if runtime is not None else ClaudeRuntime(
        panes, lambda card: None, root=root)
    events = events if events is not None else FilesEvents(root / "events")

    role = "worker"
    try:
        role = reg.get(me).role
    except Exception as e:  # noqa: BLE001 — unknown identity: the safe role
        # LOUD. Degrading to `worker` disables BOTH Rule Zero and hibernate, so a
        # silent fall-through here makes a coordinator quietly stop coordinating —
        # the same shape as the failures this whole module is consolidating. Fail
        # open, but never fail open quietly.
        print(f"stop_policy: could not read my own card ({e!r}) — treating "
              f"{me!r} as a worker, so Rule Zero and hibernate are OFF this stop",
              file=sys.stderr)

    pending = list(events.pending(me))
    # WHO IS MID-FLIGHT — measured once, here, in the same sweep as every other
    # rank, so the block decision and the drain that follows it cannot disagree
    # about who is busy. A failure to measure leaves the sender OUT of the set,
    # i.e. treated as deliverable: same fail-open as `_drain` without a pane
    # backend. `_liveness` is imported rather than reimplemented on purpose —
    # two copies of this predicate is how rank 4 and the drain drifted apart.
    busy: set = set()
    for name in {e.frm for e in pending}:
        try:
            if stop_event._liveness(reg, panes, runtime.shows_ready_ui,
                                    name) == triage.BUSY:
                busy.add(name)
        except Exception as e:  # noqa: BLE001 — unreadable pane is not busy
            print(f"stop_policy: could not read liveness for {name!r} ({e!r}) "
                  f"— treating as deliverable", file=sys.stderr)
    # Consume before deciding: an ALLOW must not leave obsolete events to
    # wake the administrator later when the sender becomes idle again.
    discarded = {e.id for e in stop_event.discard_busy(events, me, busy, pending)}
    pending = [e for e in pending if e.id not in discarded]
    inp = Inputs(me=me, role=role, pending=pending, busy_senders=busy)

    if role != "administrator":
        # Rule Zero and hibernate are the coordinator's. A lead's drain is how it
        # ABSORBS its reports; sleeping it would hold back the absorbing half of
        # the tier while the delegating half kept running.
        return inp

    # Rule Zero and rank 2a must judge the same board snapshot. Include my
    # plate in Rule Zero's scoped read so rank 2a never needs a second query.
    queue = None

    def queue_reader(*, owners):
        nonlocal queue
        if queue is None:
            queue = feed_mod.queue_state(root, reg, owners=sorted(set(owners) | {me}))
        return queue

    try:
        free, ready, held = feed_mod.gate_inputs(
            root, reg, panes, runtime, me, queue_reader=queue_reader)
        inp.free_feedable, inp.dispatchable = free, ready
        inp.throttled = len(held)
        inp.throttled_ids = {item[0] for item in held}
        inp.throttled_why = held[0][2] if held else ""
    except Exception as exc:      # noqa: BLE001 — fail open: no gate, no block
        print(f"stop_policy: Rule Zero feed-path read FAILED ({exc!r}) — "
              "ALLOWING this stop because the gate cannot prove work is dispatchable",
              file=sys.stderr)
        inp.free_feedable, inp.dispatchable = [], 0

    cfg, err = config.load_or_default(root)
    try:
        slots = ephemeral_free_slots(root)
        # No possible capacity, no board read: the rank could not fire.
        if inp.free_feedable or slots or cfg.fleet.admin_self_slots:
            plate, in_flight, inp.p0_held = gather_p0(
                root, reg, me,
                p0_reader=p0_reader or (lambda: queue_reader(owners=[me])),
                held_ids=inp.p0_held_ids)
            inp.p0_plate = plate
            inp.capacity = Capacity(
                free_crew=tuple(inp.free_feedable), ephemeral_slots=slots,
                self_slots=max(0, cfg.fleet.admin_self_slots - in_flight))
            inp.p0_last = (p0_ledger or P0Ledger(root)).last(me)
    except Exception as exc:      # noqa: BLE001 — fail open: no plate, no block
        print(f"stop_policy: P0-plate read FAILED ({exc!r}) — rank 2a is OFF "
              "this stop", file=sys.stderr)
        inp.p0_plate, inp.capacity, inp.p0_held = [], Capacity(), 0
    if err:
        print(f"stop_policy: {err} — running with hibernate OFF", file=sys.stderr)
    policy = cfg.admin_wake_budget
    if policy.mode != "off" and me in policy.agents:
        inp.admin_wake_mode = policy.mode
        try:
            card = reg.get(me)
            # Read the SAME lane/account governor as dispatch; no inferred
            # Claude membership and no cross-provider quota borrowing.
            from .harness import for_card
            if for_card(card, root=root).name == "claude":
                verdict = feed_mod.haul_governor_verdict(root, card)
                if verdict is not None and not verdict.signal_lost:
                    inp.admin_usage_pct = verdict.by_window.get("seven_day")
                last = (wake_log or WakeLog(root)).last(me)
                if last is not None:
                    inp.admin_wake_elapsed = (now if now is not None else time.time()) - last
            else:
                inp.admin_wake_mode = "off"
        except Exception as exc:  # fail open, explicitly UNKNOWN
            print(f"admin_wake_budget: evidence UNKNOWN ({type(exc).__name__})",
                  file=sys.stderr)
    inp.fleet = cfg.fleet
    if cfg.fleet.max_load_per_core:
        inp.load_per_core = _load_per_core()
    if cfg.hibernate.enabled:
        inp.hibernate = cfg.hibernate
        log = wake_log if wake_log is not None else WakeLog(root)
        inp.minutes_quiet = log.minutes_since(me, now or time.time())
    return inp


def ephemeral_free_slots(root) -> int:
    """Free ephemeral-agent slots — THE PLUG for aegis-c01c.2.

    That bead ships `shantytown.ephemeral.free_slots(root) -> int` (cap minus
    running, governor-aware). Until it does, the import fails and the answer is
    0: no slots, so rank 2a counts only crew and the administrator's own slots.
    A failure inside a present module is also 0, loudly — claiming capacity we
    could not measure would demand starts that would then be refused.
    """
    try:
        from . import ephemeral  # type: ignore[attr-defined]
    except ImportError:
        return 0
    try:
        return max(0, int(ephemeral.free_slots(root)))
    except Exception as exc:  # noqa: BLE001
        print(f"stop_policy: ephemeral slot read FAILED ({exc!r}) — counting 0",
              file=sys.stderr)
        return 0


def _owner(row: dict) -> str:
    return str(row.get("assignee") or "").split("/")[-1]


def _deferred_now(row: dict, now) -> bool:
    from datetime import datetime
    value = row.get("defer_until")
    if not isinstance(value, str) or not value:
        return False
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True          # cannot show it is due: not startable
    if when.tzinfo is None:
        return True
    return when > now


def _plate_order(row: dict):
    from .protocols import rank_order
    try:
        return (int(row.get("priority", 9)),
                *rank_order(row.get("rank"), row.get("due_at"),
                            row.get("created_at")), str(row.get("id")))
    except (TypeError, ValueError):
        # Malformed rank evidence sorts last within its priority, never drops.
        return (int(row.get("priority", 9)), (True,), str(row.get("id")))


def p0_plate(ready_rows, active_rows, me: str, *, admits=None, now=None, held_ids=None):
    """(ordered P0 plate, my in-flight count, governor-held count) from rows.

    Pure over tracker rows. A row is on the plate when it is READY (the reader
    already proved open + unblocked), priority 0, not deferred into the future,
    unassigned or mine, and passes `feed_check.dispatchable`'s exclusions (epic,
    parked, feed:manual, message, ask, decision, unfeedable) — the same predicate
    Rule Zero uses, applied with the owner stripped so my own items are judged
    by it too. Unassigned items the governor's floor refuses are HELD, not
    plate: rank 2a must not demand a start that `st go` would refuse.
    """
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc)
    cands = []
    for row in ready_rows:
        try:
            prio = int(row.get("priority"))
        except (TypeError, ValueError):
            continue
        if prio != 0 or _owner(row) not in ("", me) or _deferred_now(row, now):
            continue
        cands.append(row)
    ok = {bid for bid, _ in feed_mod.dispatchable(
        set(), [{**row, "assignee": None} for row in cands])}
    plate, held = [], 0
    for row in sorted(cands, key=_plate_order):
        if row.get("id") not in ok:
            continue
        owner = _owner(row)
        if not owner and admits is not None and admits(feed_mod._Item(row)):
            held += 1
            if held_ids is not None:
                held_ids.add(str(row.get("id")))
            continue
        plate.append(P0Item(id=str(row.get("id")), title=str(row.get("title") or ""),
                            owner=owner))
    in_flight = sum(1 for row in active_rows
                    if _owner(row) == me and row.get("status", "in_progress") == "in_progress")
    return plate, in_flight, held


def gather_p0(root, reg, me: str, *, p0_reader=None, held_ids=None):
    """Read the board ONCE for rank 2a: ready rows scoped to me + unassigned,
    and my active rows. Raises; the caller fails open."""
    if p0_reader is not None:
        ready_rows, active_rows = p0_reader()
    else:
        ready_rows, active_rows = feed_mod.queue_state(root, reg, owners=[me])
    return p0_plate(feed_mod.startable_here(root, reg, ready_rows), active_rows, me,
                    admits=feed_mod.governor_admits(root), held_ids=held_ids)


def _load_per_core() -> float | None:
    """1-minute load average per CPU. None when it cannot be read — and None means
    the capacity check does not fire, because refusing to dispatch on a number we
    could not measure would be the mirror of the bug (#23)."""
    try:
        import os as _os
        cores = _os.cpu_count() or 1
        return _os.getloadavg()[0] / cores
    except Exception:      # noqa: BLE001 — no /proc/loadavg, no answer
        return None


def run(root, me: str, **kw) -> int:
    """Gather, decide, emit. Returns the process exit code (always 0 — a stop hook
    that exits non-zero is a stop hook that breaks the agent)."""
    import time
    try:
        from . import context_hint
        reg = kw.get("reg") or FilesRegistry(root / "crew")
        try:
            card = reg.get(me)
        except Exception:
            card = None  # gather owns the existing unreadable-card diagnostic
        if card is not None and context_hint.emit(root, card):
            return 0
        inp = gather(root, me, **kw)
        verdict = decide(inp)
        state = p0_ledger_update(inp, verdict)
        if state is not None and state != inp.p0_last:
            try:
                (kw.get("p0_ledger") or P0Ledger(root)).record(me, state)
            except Exception as exc:  # noqa: BLE001 — never fails a stop
                print(f"stop_policy: P0 ledger write FAILED ({exc!r})",
                      file=sys.stderr)
        if inp.admin_wake_mode != "off":
            from .admin_wake_budget import record
            record(root, inp, verdict, now=kw.get("now"))
    except Exception as e:  # noqa: BLE001 — FAIL OPEN, see the module docstring
        print(f"stop_policy: could not decide ({e!r}) — ALLOWING the stop",
              file=sys.stderr)
        return 0

    print(f"stop_policy: {'BLOCK' if verdict.block else 'ALLOW'} "
          f"({verdict.by}) — {verdict.reason}".rstrip(" —"), file=sys.stderr)

    if not verdict.block:
        return 0

    # DELIVERY. The events half runs through stop_event's existing drain, which
    # owns BLOCK-ONCE, the mid-flight deferral, and the admin workflow
    # enrichment — none of which is reimplemented here. A rank that blocks for a
    # non-event reason (Rule Zero) still drains first, because the coordinator
    # being woken should see everything waiting for it in the same turn.
    payload = _drain_payload(root, me, kw)
    reason = verdict.reason if not payload else f"{verdict.reason}\n\n{payload}"
    # THE ROOT ENFORCES THIS RULE ON THE CREW AND HAD NO CHANNEL FOR ITSELF
    # (aegis-902vnu item 3, Stiwi: "same with all st agents"). This block payload
    # is the one message a coordinator reads every turn, so it is where its own
    # depth belongs. Prepended, not appended — the drain below it is long, and a
    # handoff line at the bottom of a workflow digest is a line nobody reaches.
    if (own := _own_context_line(root, me, kw)):
        reason = f"{own}\n\n{reason}"
    print(json.dumps({"decision": "block", "reason": reason}))
    if (log := kw.get("wake_log")) is not None or True:
        try:
            (log or WakeLog(root)).record_wake(me, kw.get("now") or time.time())
        except Exception:  # noqa: BLE001 — a ledger must never fail a wake
            pass
    return 0


def _own_context_line(root, me: str, kw) -> str:
    """The coordinator's own context-high line, or '' — ONLY past the line.

    SILENT BELOW THE THRESHOLD, deliberately. handoff_text's own rule is that a
    message re-pushed every few minutes is read once and skipped forever after,
    so a depth report on every stop would train the root to skip the block
    payload — the channel that also carries its wakes and its Rule Zero verdict.

    None (a stop taken mid-turn, no footer to read) is NOT over the line, exactly
    as _my_context_k documents: unknown is not a number.
    """
    from . import handoff_text
    from .triage import CYCLE_THRESHOLD_K
    try:
        reg = kw.get("reg") or FilesRegistry(root / "crew")
        panes = kw.get("panes") or Tmux()
        depth = stop_event._my_context_k(reg, panes, me)
    except Exception:      # noqa: BLE001 — a report must never fail a wake
        return ""
    if depth is None or depth < CYCLE_THRESHOLD_K:
        return ""
    return handoff_text.coordinator_self_handoff(depth, CYCLE_THRESHOLD_K)


def _drain_payload(root, me: str, kw) -> str:
    """The drained events, rendered — or '' if there was nothing (or it failed).

    Captured rather than printed: stop_event._drain emits its own block payload on
    stdout, and TWO payloads in one hook is not a protocol. So this calls it with
    stdout redirected and lifts the reason out.
    """
    import contextlib
    import io
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            stop_event.main(["drain", "--root", str(root)])
    except Exception:      # noqa: BLE001 — a failed drain must not lose the block
        return ""
    out = buf.getvalue().strip()
    if not out:
        return ""
    try:
        return json.loads(out).get("reason", "")
    except ValueError:
        return ""


@declared_command("stop_policy")
def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    me_env = os.environ.get("SHANTY_AGENT")
    if not me_env:
        print("stop_policy: $SHANTY_AGENT is unset — cannot resolve identity",
              file=sys.stderr)
        return 1
    root = stop_event._root(argv)
    reg = FilesRegistry(root / "crew")
    panes = Tmux(socket=stop_event.declared_socket(root))
    me = stop_event._stop_identity(reg, panes, me_env)
    if me is None:
        return 1
    # RANK 0, before any verdict: route and persist MY OWN stop event upward.
    # Survival, not a decision — a verdict must not be able to lose the event.
    try:
        if reg.get(me).role != "administrator":
            stop_event.main(["send", "--root", str(root)])
    except Exception as e:  # noqa: BLE001 — reported, never swallowed
        print(f"stop_policy: could not persist my own stop event ({e!r})",
              file=sys.stderr)
    from . import agent_hold
    if agent_hold.reason(root, me):
        # Workers already reached this seam through stop_event send above.
        if reg.get(me).role == "administrator":
            agent_hold.finish_turn(root, me)
        return 0
    return run(root, me)


if __name__ == "__main__":
    raise SystemExit(main())
