"""Receipt coordinator injected into dispatch, separate from Tracker's protocol.

The existing pane adapter owns submission and composer recovery. This module
never types, presses Enter, clears a composer, or retries a native claim.
"""
from dataclasses import asdict
import hashlib
import json
import re
import time
import uuid

from .dispatch_receipts import (DifferentScope, ReceiptConflict, ReceiptStore, assignment_comment,
                                assignment_proof, assignment_supersession,
                                prepared_supersession)
from .protocols import SubmissionObserved


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def task_digest(item):
    # Assignment changes these fields in the very transition we are proving.
    # All other task data and the independent exact revision remain bound.
    return digest({k: v for k, v in asdict(item).items()
                   if k not in {'revision', 'status', 'assignee', 'defer_until', 'updated_at'}})


class FilesAssignments:
    def __init__(self, tracker):
        self.tracker = tracker

    def claim(self, row, updates):
        if (updates.get('status') != 'in_progress' or updates.get('assignee') != row['worker']
                or updates.get('defer_until') not in (None, '')
                or set(updates) - {'status', 'assignee', 'defer_until'}):
            raise ReceiptConflict('dispatch assignment fields differ from receipt')
        self.tracker.update(row['item'], **updates, if_revision=row['revision'],
                            transition_comment=assignment_comment(row))
        return self.read(row)

    def read(self, row):
        # Same atomic file contains revision, assignment and transition comment.
        current = json.loads(self.tracker._path(row['item']).read_text())
        return assignment_proof(row, dict(current, id=row['item']))

    def supersession(self, row):
        current = json.loads(self.tracker._path(row['item']).read_text())
        prove = prepared_supersession if row['state'] == 'prepared' else assignment_supersession
        return prove(row, dict(current, id=row['item']))


class SeedsAssignments:
    def __init__(self, tracker):
        self.tracker = tracker

    def claim(self, row, updates):
        return self.tracker.dispatch_assignment(row, updates)

    def read(self, row):
        return self.tracker.dispatch_assignment_read(row)

    def supersession(self, row):
        prove = prepared_supersession if row['state'] == 'prepared' else assignment_supersession
        return prove(row, self.tracker.stranded_read(row['item']))


class Binding:
    def __init__(self, root, tracker, registry, panes, assignments):
        self.store = ReceiptStore(root)
        self.tracker, self.registry, self.panes = tracker, registry, panes
        self.assignments = assignments

    def request(self, plan, agent):
        runtime = self.panes.runtime_identity(plan.pane)
        if not runtime:
            raise ReceiptConflict('dispatch runtime process identity UNKNOWN')
        return dict(note=plan.note, store=plan.store, nodes=plan.quipu_nodes,
                    sender=plan.sender, worker_sha256=digest(asdict(agent)), runtime=runtime)

    def scope(self, plan, *, current=False):
        item = self.tracker.get(plan.item_id) if current else plan.binding_item
        agent = self.registry.get(plan.agent) if current else plan.binding_agent
        if item is None or agent is None or agent.pane != plan.pane:
            raise ReceiptConflict('dispatch task or worker identity UNKNOWN')
        request = self.request(plan, agent)
        return ReceiptStore._scope(dict(item=plan.item_id, revision=item.revision,
            worker=plan.agent, pane=plan.pane, session=self.panes.session_created(plan.pane),
            task_sha256=task_digest(item), scope_sha256=digest(request)))

    def observed(self, row):
        """Adapter-owned positive proof; absence leaves the original fence."""
        observer = getattr(self.panes, 'observed_submission', None)
        if callable(observer):
            return observer(row['pane'], row['text'], row['session'], row['created'],
                            row['request']['runtime'], row['worker'])
        from .delivery import observed_submission
        return observed_submission(self.store.root.parent, row['pane'],
            getattr(self.panes, 'socket', None), row['text'], row['session'], row['created'],
            row['request']['runtime'])

    def complete(self, plan, ident, *, dry_run=False):
        """Finish the original send/claim only; never compose or send another body."""
        row = self.store.read(ident)
        if row['item'] != plan.item_id or row['worker'] != plan.agent:
            raise ReceiptConflict('receipt names a different task or worker')
        request = row.get('request')
        if not isinstance(request, dict) or digest(request) != row['scope_sha256']:
            raise ReceiptConflict('receipt request metadata UNKNOWN')
        plan.note, plan.store = request['note'], request['store']
        plan.quipu_nodes, plan.sender = request['nodes'], request['sender']
        plan.receipt_id, plan.text, plan.replayed = ident, row['text'], True
        scope = self.scope(plan, current=True)
        expected = self.store._scope(row)
        if row['state'] in ('assigning', 'assigned'):
            proof = self.assignments.read(row)
            expected = dict(expected, revision=proof['revision'])
        if scope != expected or row['state'] == 'superseded':
            raise ReceiptConflict('stale task, worker, runtime or scope')
        if dry_run:
            return self.reconcile(ident)
        with self.store.lock(row['item']):
            # Lock and re-read before each write; no uncertain claim is repeated.
            row = self.store.read(ident)
            if self.scope(plan, current=True) != expected:
                raise ReceiptConflict('scope changed before receipt completion')
            if row['state'] == 'prepared':
                observed = self.observed(row)
                if observed is None:
                    raise ReceiptConflict('submission unconfirmed; original receipt retained, no resend')
                self.store.submitted(ident, observed)
            elif row['state'] == 'assigning':
                self.store.recover_assignment(ident, self.assignments.read(row))
            self.assign(plan)
        return self.reconcile(ident)

    def prepare(self, plan):
        scope = self.scope(plan)
        with self.store.lock(plan.item_id):
            pending = self.store.pending(plan.item_id)
            if pending and pending['state'] == 'prepared' and self.store._scope(pending) == scope:
                observed = self.observed(pending)
                if observed is not None:
                    self.store.submitted(pending['id'], observed)
                    pending = self.store.read(pending['id'])
            if pending and pending['state'] == 'assigning':
                try:
                    proof = self.assignments.read(pending)
                except Exception as error:
                    raise ReceiptConflict('native assignment outcome UNKNOWN; reconcile before retry') from error
                expected = dict(ReceiptStore._scope(pending), revision=proof['revision'])
                if scope != expected:
                    raise ReceiptConflict('native receipt exists for a stale scope')
                self.store.recover_assignment(pending['id'], proof)
            prior = self.store.find(scope)
            # The generated serve marker/advice are attempt artifacts. A replay
            # carries the original immutable body, never freshly composed text.
            if prior:
                text, ident = prior['text'], prior['id']
            else:
                ident = plan.serve_id or uuid.uuid4().hex
                marker = f'[st serve:{ident} worker:{plan.agent}]'
                original = re.sub(r' — \[st serve:[0-9a-f]{32} worker:[^\]]+\]$', '', plan.text)
                text = (original + f' — Dispatch receipt {ident} is PENDING; before execution run '
                        f'st go {plan.item_id} {plan.agent} --reconcile --receipt {ident}; '
                        'proceed only when execution_authorized is true. Never resend or claim by hand.'
                        f' — {marker}')
            try:
                row, fresh = self.store.prepare(scope, text, ident=ident)
            except DifferentScope as error:
                # A recovery hint is not release proof: the command still runs
                # its own native guards if an operator explicitly chooses it.
                try:
                    current = self.tracker.get(plan.item_id)
                except Exception:
                    current = None
                if (current is not None and current.status == 'open'
                        and not current.assignee and not current.defer_until
                        and error.receipt['state'] in ('prepared', 'assigning')):
                    raise DifferentScope(error.receipt, supersede_hint=True) from None
                raise
            if fresh:
                row['request'] = self.request(plan, plan.binding_agent)
                self.store._save(row)
            plan.receipt_id = row['id']
            plan.text = row['text']
            match = re.search(r'\[st serve:([0-9a-f]{32}) worker:[^\]]+\]$', plan.text)
            plan.serve_id = match[1] if match else ''
            plan.replayed = not fresh
            if not fresh and row['state'] in ('prepared', 'assigning'):
                raise ReceiptConflict(f"receipt {row['id']} pending; reconcile retained evidence before retry")
            return fresh

    def submitted(self, plan, observed):
        self.store.submitted(plan.receipt_id, observed)

    def confirm_submission(self, plan, observed):
        """Observe the one initial send; never type, complete or claim here."""
        if isinstance(observed, SubmissionObserved) and observed.matches(plan.pane, plan.text):
            return observed
        if observed is not None or not callable(getattr(self.panes, 'observed_submission', None)):
            return None
        row = self.store.read(plan.receipt_id)
        expected = self.store._scope(row)
        if (row['state'] != 'prepared' or row['item'] != plan.item_id
                or row['worker'] != plan.agent or row['text'] != plan.text):
            raise ReceiptConflict('initial submission receipt differs from dispatch')
        if self.scope(plan, current=True) != expected:
            raise ReceiptConflict('scope changed before observing initial submission')
        # A measured native Claude user record arrived 0.33s after preparation,
        # while the echo-only path missed it. Poll the existing exact native reader,
        # bounded by BOTH attempts and elapsed time; missing proof stays pending.
        deadline = time.monotonic() + 5
        for attempt in range(11):
            if attempt and time.monotonic() >= deadline:
                return None
            proof = self.observed(row)
            if isinstance(proof, SubmissionObserved) and proof.matches(plan.pane, plan.text):
                if self.scope(plan, current=True) != expected:
                    raise ReceiptConflict('scope changed while observing initial submission')
                return proof
            remaining = deadline - time.monotonic()
            if attempt == 10 or remaining <= 0:
                return None
            time.sleep(min(0.5, remaining))

    def assign(self, plan):
        row = self.store.read(plan.receipt_id)
        current = self.scope(plan, current=True)
        if row['state'] == 'assigned':
            try:
                proof = self.assignments.read(row)
            except Exception as error:
                raise ReceiptConflict('native assignment read-back UNKNOWN') from error
            if current != dict(self.store._scope(row), revision=proof['revision']):
                raise ReceiptConflict('assigned receipt scope is stale')
        return self.store.assign(plan.receipt_id, current,
                                 lambda row: self.assignments.claim(row, plan.updates))

    def supersede(self, ident, *, dry_run=False):
        """Explicitly retire an attempt; never send, claim or authorize work."""
        row = self.store.read(ident)
        if dry_run:
            # A preview must not acquire a writable ledger lock or remove the
            # interrupted-assignment fence. Native release evidence is still
            # required; this read never authorizes a later transition.
            if row['state'] not in ('prepared', 'assigning', 'superseded'):
                raise ReceiptConflict('only a prepared intent or fenced assignment can be superseded')
            if row['state'] in ('prepared', 'assigning'):
                self.assignments.supersession(row)
            return dict(id=ident, state=row['state'], dry_run=True,
                        would_supersede=row['state'] != 'superseded', execution_authorized=False)
        with self.store.lock(row['item']):
            if row['state'] == 'superseded':
                return dict(id=ident, state='superseded', execution_authorized=False)
            proof = self.assignments.supersession(row)
            self.store.supersede_assignment(ident, proof)
        return dict(id=ident, state='superseded', execution_authorized=False)

    def reconcile(self, ident):
        """Read-only, including when local assignment persistence was interrupted."""
        row = self.store.read(ident)
        current = self.tracker.get(row['item'])
        agent = self.registry.get(row['worker'])
        request = row.get('request')
        if not isinstance(request, dict) or digest(request) != row['scope_sha256']:
            raise ReceiptConflict('receipt request metadata UNKNOWN')
        scope = dict(row, revision=current.revision, pane=agent.pane,
                     session=self.panes.session_created(agent.pane), task_sha256=task_digest(current))
        scope['scope_sha256'] = digest(dict(request, worker_sha256=digest(asdict(agent)),
                                          runtime=self.panes.runtime_identity(agent.pane)))
        # Reconstruct the original request from the stored public scope inputs.
        # A fresh registry identity must still agree; status never guesses that
        # a changed card is the same assignment.
        status = self.store.status(ident, scope)
        status.update(item=row['item'], worker=row['worker'], native_assignment='UNKNOWN')
        status['execution_authorized'] = False
        if row['state'] == 'superseded':
            return status
        try:
            proof = self.assignments.read(row)
        except Exception as error:
            status['native_reason'] = type(error).__name__
        else:
            status['native_assignment'] = proof
            expected = dict(ReceiptStore._scope(row), revision=proof['revision'])
            if ReceiptStore._scope(scope) == expected and row['submission']:
                status['execution_authorized'] = True
                if not row['assignment']:
                    status['state'] = 'native_assigned'
                    status['missing'] = ['local_assignment']
        return status


def binding_for(root, tracker, registry, panes):
    from .sd import SdTracker
    from .files import FilesTracker
    if isinstance(tracker, SdTracker):
        assignments = SeedsAssignments(tracker)
    elif isinstance(tracker, FilesTracker):
        assignments = FilesAssignments(tracker)
    else:
        # Older adapters have no revision/CAS contract. Their legacy dispatch
        # remains explicit; they cannot emit a bound execution receipt.
        return None
    return Binding(root, tracker, registry, panes, assignments)
