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


class Refiller:
    def __init__(self, root, reg, panes, runtime, *, snapshot, preview, dispatch,
                 log=print, clock=time.time, budget=45, free=None, coverage=lambda: True):
        self.root, self.reg, self.panes, self.runtime = Path(root), reg, panes, runtime
        self.snapshot, self.preview, self.dispatch = snapshot, preview, dispatch
        self.log, self.clock, self.budget = log, clock, budget
        self.free = free
        self.coverage = coverage

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
        for worker in free:
            if time.monotonic() - started >= self.budget:
                observations[worker] = {'at': self.clock(), 'state': 'budget-exhausted'}
                continue
            # Rotate after an attempted member, including an UNKNOWN preview;
            # otherwise a slow first member starves the rest on every tick.
            state['last_worker'] = worker
            for row in rows:
                if time.monotonic() - started >= self.budget:
                    observations[worker] = {'at': self.clock(), 'state': 'budget-exhausted'}
                    break
                item = row['id']
                if item in reserved:
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
                    continue
                # Persist before sending: timeout/exit 2 can follow a delivered
                # pane message. Never give that item or worker a competing send.
                pending[worker] = {'item': item, 'at': self.clock()}
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
                if rc == 0:
                    delivered.append(worker)
                # A refused real dispatch can mean the pane just became busy.
                # Do not try another item on this worker in the same pass.
                break
            observations.setdefault(worker, {'at': self.clock(), 'state': 'no-eligible-item'})
        state['observed_at'] = self.clock()
        state['observations'] = observations
        state['waiting'] = waiting
        write_json_atomic(path, state)
        with (directory / 'observations.jsonl').open('a') as journal:
            journal.write(json.dumps({'at': state['observed_at'], 'observations': observations,
                                      'pending': pending}, sort_keys=True) + '\n')
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
        return sorted(set(local) | remote)
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
                      coverage=lambda: not peer_errors).sweep()
    report(a.root, reg, panes, log=log)
    return result
