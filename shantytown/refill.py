"""Feed unowned ready work through normal dispatch on the existing tend tick.

# arming: library; the fleet-owner tend sweep, not an agent or a new scheduler.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import time

from . import feed_check
from .files import write_json_atomic
from .priority_advisory import priority, workable
from .protocols import rank_order


def ordered(rows):
    """The ready projection selects candidates; dispatch re-reads each item."""
    ids = {ident for ident, _ in feed_check.dispatchable(set(), rows)}
    return sorted((row for row in rows if row.get('id') in ids
                   and row.get('status', 'open') == 'open'
                   and priority(row) in range(5) and workable(row)
                   and not row.get('defer_until')),
                  key=lambda r: (priority(r), rank_order(r.get('rank'),
                      r.get('due_at'), r.get('created_at')), r['id']))


# aegis-6vto.6 (Stiwi 2026-11-11, two-week trial): about 20% of live capacity
# for Now (interrupts and new asks), 60% for Next in rank order, 20% for Later
# oldest-first. Unused Now share works Next. A missing lane is UNLANED (6vto.4
# plate semantics): it is served inside the Next share after laned Next items,
# in ordered() order, so before any lane is populated the order is today's.
LANES = ('now', 'next', 'later')


def lane(row):
    value = row.get('lane')
    value = value.strip().lower() if isinstance(value, str) else ''
    return value if value in LANES else ''


def quotas(members):
    """Member slots per lane; Now always keeps one slot while anyone is live."""
    if members <= 0:
        return dict(now=0, next=0, later=0)
    now = max(1, int(members * 0.2 + 0.5))
    later = min(int(members * 0.2 + 0.5), members - now)
    return dict(now=now, next=members - now - later, later=later)


def _owner(row):
    # Trailing-segment match, the same parse feed_check.hauls uses.
    return (row.get('assignee') or '').rsplit('/', 1)[-1]


def occupancy(active, members):
    """Members whose in-hand (in_progress) work sits in each lane; one per member."""
    seen, counts = set(), dict(now=0, next=0, later=0)
    for row in sorted(active, key=lambda r: str(r.get('id'))):
        who = _owner(row)
        if (row.get('status') != 'in_progress' or not who or who in seen
                or who not in members):
            continue
        seen.add(who)
        counts[lane(row) or 'next'] += 1
    return counts


def _oldest(row):
    return (str(row.get('lane_entered_at') or row.get('laneEnteredAt')
                or row.get('created_at') or ''), row['id'])


def lane_sequence(rows, quota, occupied):
    """Candidate order for ONE free member, and the lane its first item serves.

    Lanes under their share come first (Now, then Later), then Next (laned by
    rank, then unlaned), then any lane already at its share. Nothing is left
    idle because of the split: every candidate stays reachable."""
    groups = dict(now=sorted((r for r in rows if lane(r) == 'now'), key=_oldest),
                  later=sorted((r for r in rows if lane(r) == 'later'), key=_oldest),
                  next=[r for r in rows if lane(r) == 'next']
                       + [r for r in rows if not lane(r)])
    under = [name for name in ('now', 'later')
             if occupied[name] < quota[name] and groups[name]]
    over = [name for name in ('now', 'later') if name not in under]
    order = under + ['next'] + over
    return [(name, row) for name in order for row in groups[name]]


class Refiller:
    def __init__(self, root, reg, panes, runtime, *, snapshot, preview, dispatch,
                 log=print, clock=time.time, budget=45, free=None, coverage=lambda: True,
                 members=None):
        self.root, self.reg, self.panes, self.runtime = Path(root), reg, panes, runtime
        self.snapshot, self.preview, self.dispatch = snapshot, preview, dispatch
        self.log, self.clock, self.budget = log, clock, budget
        self.free = free
        self.coverage = coverage
        # Live worker/lead names for the capacity split; None = free members
        # plus the owners of active work (a test seam, not a census).
        self.members = members

    def sweep(self):
        """One item per idle member; uncertain sends retain exclusive custody."""
        directory = self.root / 'refill'
        directory.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(directory / 'lock', os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return []
            return self._sweep(directory)

    def _sweep(self, directory):
        path = directory / 'state.json'
        state = json.loads(path.read_text()) if path.exists() else {'pending': {}}
        pending = state['pending']
        try:
            free = (self.free() if self.free is not None else
                    feed_check.free_feedable_workers(self.reg, self.panes, self.runtime,
                        root=self.root, roles=('worker', 'lead')))
            ready, active = self.snapshot()
        except Exception as exc:
            state.update(observed_at=self.clock(), observation_error=type(exc).__name__)
            write_json_atomic(path, state)
            self.log(f'auto-refill UNKNOWN ({type(exc).__name__}); no dispatch')
            return []
        state.pop('observation_error', None)
        state['coverage'] = self.coverage()
        # Bounded snapshot readers have their own deadlines. Charging their
        # latency to selection can exhaust every tick before its first attempt.
        started = time.monotonic()
        # An existing workable queue belongs to haul, including active work.
        # A blocked plate does not monopolize the member's remaining capacity.
        queues = feed_check.hauls([row for row in ready if workable(row)],
                                 [row for row in active if workable(row)])
        owned_idle = [name for name in free if queues.get(name) and name not in pending]
        free = [name for name in free if not queues.get(name) and name not in pending]
        after = state.get('last_worker')
        if after in free:
            index = free.index(after) + 1
            free = free[index:] + free[:index]
        rows = ordered(ready)
        fallback = {*free, *owned_idle, *pending,
                    *(_owner(row) for row in active if _owner(row))}
        census = 'fallback'
        live = fallback
        if self.members is not None:
            try:
                # A census can only add capacity the tick already sees as free.
                live, census = set(self.members()) | set(free) | set(owned_idle), 'live'
            except Exception as exc:
                census = f'unknown:{type(exc).__name__}'
                self.log(f'auto-refill split census UNKNOWN ({type(exc).__name__}); '
                         'using free members plus active owners')
        quota = quotas(len(live))
        occupied = occupancy(active, live)
        for entry in pending.values():
            occupied[entry.get('lane') or 'next'] += 1
        split = dict(members=len(live), census=census, quota=quota, occupied_before=dict(occupied),
                     waiting={name: sum(1 for r in rows if (lane(r) or 'next') == name)
                              for name in LANES},
                     served=dict(now=0, next=0, later=0))
        reserved = {entry['item'] for entry in pending.values()}
        delivered, observations = [], {}
        waiting = {}
        by_id = {row['id']: row for row in [*ready, *active]}
        for worker in owned_idle:
            if feed_check.haul_hold_reason(self.root, worker):
                observations[worker] = {'at': self.clock(), 'state': 'held'}
                continue
            item = queues[worker][0]
            if item not in by_id:
                continue
            previous = state.get('waiting', {}).get(worker, {})
            since = previous.get('since', self.clock()) if previous.get('item') == item else self.clock()
            waiting[worker] = {'item': item, 'since': since}
            observations[worker] = {'at': self.clock(), 'item': item,
                                    'state': 'own-queue', 'idle_seconds': self.clock() - since}
        # Per-worker lap memory (review az0, PR434): items already judged
        # ineligible for that worker in the current pass through the candidate
        # list. Each tick resumes past them, so slow readable previews of an
        # ineligible prefix cannot exhaust every tick's budget before a later
        # eligible item is reached. Scans stay in priority order, so new or
        # higher-ranked work is still seen first.
        #
        # A lap ends only when every candidate has been judged or on a dispatch
        # attempt; there is deliberately NO per-entry age limit. Each tick
        # previews at least one unjudged item, so a lap always completes, and a
        # judged item is re-read at the next lap. An age limit shorter than the
        # lap would re-expire the head before the tail is reached and starve it
        # again (review az0 R1: 26-item prefix, 24 s previews, 300 s ticks).
        # Bounded by the live candidate set and the free workers.
        current = {row['id'] for row in rows}
        laps = {}
        for worker, seen in state.get('lap', {}).items():
            if worker in free:
                kept = {item: at for item, at in seen.items() if item in current}
                if kept:
                    laps[worker] = kept
        for worker in free:
            if time.monotonic() - started >= self.budget:
                observations[worker] = {'at': self.clock(), 'state': 'budget-exhausted'}
                continue
            # Rotate after an attempted member, including an UNKNOWN preview;
            # otherwise a slow first member starves the rest on every tick.
            state['last_worker'] = worker
            seen = laps.setdefault(worker, {})
            for served_lane, row in lane_sequence(rows, quota, occupied):
                if time.monotonic() - started >= self.budget:
                    observations[worker] = {'at': self.clock(), 'state': 'budget-exhausted'}
                    break
                item = row['id']
                if item in reserved or item in seen:
                    continue
                if feed_check.haul_hold_reason(self.root, worker):
                    observations[worker] = {'at': self.clock(), 'state': 'held'}
                    break
                try:
                    allowed = self.preview(item, worker)
                except Exception as exc:
                    observations[worker] = {'at': self.clock(), 'state': 'preview-unknown',
                                            'detail': type(exc).__name__}
                    break
                if not allowed:
                    seen[item] = self.clock()
                    continue
                # Persist before sending: timeout/exit 2 can follow a delivered
                # pane message. Never give that item or worker a competing send.
                # Any dispatch attempt changes the worker's state: start a new lap.
                seen.clear()
                state['lap'] = {w: v for w, v in laps.items() if v}
                pending[worker] = {'item': item, 'at': self.clock(), 'lane': served_lane}
                occupied[served_lane] += 1
                state['last_worker'] = worker
                write_json_atomic(path, state)
                reserved.add(item)
                try:
                    rc = self.dispatch(item, worker)
                except Exception as exc:
                    rc = 2
                    self.log(f'auto-refill {worker} dispatch UNKNOWN ({type(exc).__name__})')
                observations[worker] = {'at': self.clock(), 'item': item,
                    'state': 'delivered' if rc == 0 else 'refused' if rc == 1 else 'unknown'}
                if rc in (0, 1):
                    pending.pop(worker)
                if rc == 1:
                    occupied[served_lane] -= 1
                if rc == 0:
                    delivered.append(worker)
                    split['served'][served_lane] += 1
                # A refused real dispatch can mean the pane just became busy.
                # Do not try another item on this worker in the same pass.
                break
            else:
                # The whole candidate list was judged: the next tick starts a new lap.
                seen.clear()
            observations.setdefault(worker, {'at': self.clock(), 'state': 'no-eligible-item'})
        state['observed_at'] = self.clock()
        state['lap'] = {w: v for w, v in laps.items() if v}
        state['observations'] = observations
        state['waiting'] = waiting
        # The trial's report reads these (6vto.6): Now ran DRY = Now work was
        # waiting with its share full; Now sat IDLE = share free, nothing in Now.
        split['occupied_after'] = dict(occupied)
        split['now_dry'] = int(split['waiting']['now'] > split['served']['now']
                               and occupied['now'] >= quota['now'])
        split['now_idle'] = int(split['waiting']['now'] == 0
                                and split['occupied_before']['now'] < quota['now'])
        state['split'] = split
        write_json_atomic(path, state)
        with (directory / 'observations.jsonl').open('a') as journal:
            journal.write(json.dumps({'at': state['observed_at'], 'observations': observations,
                                      'pending': pending, 'split': split},
                                     sort_keys=True) + '\n')
        for worker, observation in observations.items():
            self.log(f"auto-refill {worker}: {observation['state']} {observation.get('item', '')}")
        return delivered


def metrics(root, now):
    """Persisted natural observations; missing/stale coverage never means zero idle."""
    path = Path(root) / 'refill' / 'state.json'
    if not path.exists():
        return ''
    state = json.loads(path.read_text())
    pending = state['pending']
    age = max([0] + [max(0, now - entry['at']) for entry in pending.values()])
    known = int(0 <= now - state['observed_at'] <= 900 and not pending
                and not state.get('observation_error') and state.get('coverage') is True
                and all(row['state'] not in {'preview-unknown', 'unknown', 'refused', 'budget-exhausted'}
                        for row in state.get('observations', {}).values()))
    idle = max([0] + [row.get('idle_seconds', 0) for row in state.get('observations', {}).values()])
    return (f"st_refill_observation_timestamp_seconds {state['observed_at']}\n"
            f"st_refill_observation_known {known}\n"
            f"st_refill_owned_queue_idle_seconds {idle}\n"
            f"st_refill_pending_dispatches {len(pending)}\n"
            f"st_refill_pending_oldest_seconds {age}\n")


def report(root, reg, panes, *, log=print):
    """Use the existing changed-digest alert path, including UNKNOWN coverage."""
    from .creel_advisory import Advice, Alerter
    path = Path(root) / 'refill' / 'state.json'
    state = json.loads(path.read_text())
    bad = {worker for worker, row in state.get('observations', {}).items()
           if row['state'] in {'preview-unknown', 'unknown', 'refused', 'budget-exhausted'}
           or row.get('idle_seconds', 0) >= 900}
    bad.update(state['pending'])
    if state.get('observation_error') or state.get('coverage') is not True:
        bad.add('observation-coverage')
    bad = sorted(bad)
    text = ('Automatic refill unresolved for ' + ', '.join(bad)
            if bad else 'Automatic refill observations are current; no unresolved dispatch')
    return Alerter(root, reg, panes, filename='auto_refill.json',
                   label='automatic work refill').sweep(
                       {'fleet': Advice(text, '|'.join(bad) or 'clear', failure=bool(bad), risk=2)})


def from_cli(a, reg, panes, runtime, cfg, *, log=print):
    """Use existing host routing and normal dispatch; never start a peer feeder."""
    import argparse
    from .cli import _cmd_go, _wire, _tracker, OK, CANNOT_TELL
    from .answer import CouldNotLook
    from .dispatch import Closed, Blocked, HasOpenBlocker, AlreadyAssigned, GovernorRefused
    from .triage import Action
    from . import feed_check, fleet as fleet_census
    remote = set()
    remote_live = set()
    peer_errors = []
    def free():
        local = feed_check.free_feedable_workers(reg, panes, runtime,
            root=a.root, roles=('worker', 'lead'))
        results = fleet_census.collect(cfg.host_peers)
        peer_errors.extend(fleet_census.errors(results))
        for error in peer_errors:
            log(f'auto-refill peer coverage UNKNOWN: {error}')
        remote.update(row['name'] for row in fleet_census.rows(results)
            if row['live'] and row['work'] == 'idle' and row['state'] == 'up'
            and not row.get('retired')
            and row.get('tree_role', row['role']) in ('worker', 'lead'))
        remote_live.update(row['name'] for row in fleet_census.rows(results)
            if row['live'] and row['state'] == 'up' and not row.get('retired')
            and row.get('tree_role', row['role']) in ('worker', 'lead'))
        return sorted(set(local) | remote)
    def members():
        # Capacity for the 6vto.6 split: live worker/lead panes, busy or idle,
        # by the cheap card gates (no screen capture), plus live peer rows.
        from .tend import is_retired
        from .ephemeral import is_ephemeral_name
        local = {ag.name for ag in reg.all().exact()
                 if getattr(ag, 'role', None) in ('worker', 'lead')
                 and getattr(ag, 'pane', None) and panes.exists(ag.pane)
                 and not is_retired(ag) and not is_ephemeral_name(ag.name)}
        return sorted(local | remote_live)
    def args_for(item, worker, *, dry_run):
        return argparse.Namespace(**(vars(a) | dict(item=item, agent=worker,
            dry_run=dry_run, note=None, note_file=None, reassign=False,
            worktree=None, quipu_node=[], no_graph_context=(
                'Automatic refill read the exact tracker item; ontology subject '
                'selection is left to the recipient query-first step, not guessed.'))))
    def snapshot():
        owners = [c.name for c in reg.all().exact()] + sorted(remote)
        ready = feed_check.tend_ready(a.root, reg, owners)
        active = feed_check.tend_active(a.root, reg, owners=owners)
        return ready, active
    def preview(item, worker):
        try:
            current = _tracker(a).get(item)
            if (current.id != item or current.status != 'open'
                    or current.assignee or current.defer_until
                    or any(label.startswith(('blocked:', 'parked:'))
                           for label in current.labels)):
                return False
            if worker in remote:
                rc = _cmd_go(args_for(item, worker, dry_run=True))
                if rc == CANNOT_TELL:
                    raise CouldNotLook('peer dispatch preview unavailable')
                return rc == OK
            dispatcher = _wire(a)
            return dispatcher.triage(item, worker).action is Action.NUDGE
        except (Closed, Blocked, HasOpenBlocker, AlreadyAssigned, GovernorRefused):
            return False
    def dispatch(item, worker):
        # Reuse the public command's graph, hold, pane, governor,
        # capacity, send/readback and tracker-write checks unchanged.
        return _cmd_go(args_for(item, worker, dry_run=False))
    result = Refiller(a.root, reg, panes, runtime, snapshot=snapshot,
                      preview=preview, dispatch=dispatch, log=log, free=free,
                      coverage=lambda: not peer_errors, members=members).sweep()
    report(a.root, reg, panes, log=log)
    return result
