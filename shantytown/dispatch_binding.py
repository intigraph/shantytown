"""Receipt coordinator injected into dispatch, separate from Tracker's protocol.

The existing pane adapter owns submission and composer recovery. This module
never types, presses Enter, clears a composer, or retries a native claim.
"""
from dataclasses import asdict
import hashlib
import json
import re
import uuid

from .dispatch_receipts import ReceiptConflict, ReceiptStore, assignment_comment, assignment_proof


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
        self.tracker.update(row['item'], **updates, if_revision=row['revision'],
                            transition_comment=assignment_comment(row))
        return self.read(row)

    def read(self, row):
        # Same atomic file contains revision, assignment and transition comment.
        current = json.loads(self.tracker._path(row['item']).read_text())
        return assignment_proof(row, dict(current, id=row['item']))


class SeedsAssignments:
    def __init__(self, tracker):
        self.tracker = tracker

    def claim(self, row, updates):
        return self.tracker.dispatch_assignment(row, updates)

    def read(self, row):
        return self.tracker.dispatch_assignment_read(row)


class Binding:
    def __init__(self, root, tracker, registry, panes, assignments):
        self.store = ReceiptStore(root)
        self.tracker, self.registry, self.panes = tracker, registry, panes
        self.assignments = assignments

    @staticmethod
    def request(plan, agent):
        return dict(note=plan.note, store=plan.store, nodes=plan.quipu_nodes,
                    sender=plan.sender, worker_sha256=digest(asdict(agent)))

    def scope(self, plan, *, current=False):
        item = self.tracker.get(plan.item_id) if current else plan.binding_item
        agent = self.registry.get(plan.agent) if current else plan.binding_agent
        if item is None or agent is None or agent.pane != plan.pane:
            raise ReceiptConflict('dispatch task or worker identity UNKNOWN')
        request = self.request(plan, agent)
        return ReceiptStore._scope(dict(item=plan.item_id, revision=item.revision,
            worker=plan.agent, pane=plan.pane, session=self.panes.session_created(plan.pane),
            task_sha256=task_digest(item), scope_sha256=digest(request)))

    def prepare(self, plan):
        scope = self.scope(plan)
        with self.store.lock(plan.item_id):
            pending = self.store.pending(plan.item_id)
            if pending and pending['state'] == 'assigning':
                proof = self.assignments.read(pending)
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
            row, fresh = self.store.prepare(scope, text, ident=ident)
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

    def assign(self, plan):
        return self.store.assign(plan.receipt_id, self.scope(plan, current=True),
                                 lambda row: self.assignments.claim(row, plan.updates))

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
        scope['scope_sha256'] = digest(dict(request, worker_sha256=digest(asdict(agent))))
        # Reconstruct the original request from the stored public scope inputs.
        # A fresh registry identity must still agree; status never guesses that
        # a changed card is the same assignment.
        status = self.store.status(ident, scope)
        status.update(item=row['item'], worker=row['worker'], native_assignment='UNKNOWN')
        status['execution_authorized'] = False
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
