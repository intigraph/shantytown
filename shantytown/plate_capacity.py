"""Bounded assignment admission; a partial plate is never spare capacity."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import fcntl
from functools import wraps
import hashlib
import json
import threading
from pathlib import Path

from .inbox import is_anchor, is_message, _deferred_until_is_future

MAX_ACTIVE = 10
ACTIVE = frozenset({'open', 'hooked', 'in_progress', 'blocked'})


class CapacityUnknown(ValueError):
    pass


class PlateFull(ValueError):
    pass


def owner_name(owner):
    return (owner or '').strip().rstrip('/').rsplit('/', 1)[-1]


def real_work(row):
    """Messages and detector records are delivery, not implementation slots.

    Match the producers' explicit labels and legacy title prefixes. A bug filed
    to repair an alarm remains work unless it carries a detector record marker.
    """
    title = (row.get('title') or '').lstrip()
    labels = row.get('labels') or []
    if isinstance(labels, str):
        labels = labels.split(',')
    labels = {str(v.get('name', '') if isinstance(v, dict) else v).strip() for v in labels}
    return (not is_message(title)
            and not labels.intersection({'inbox', 'inbox-body', 'mail', 'alarm', 'alerting', 'recurring-alarm'})
            and not title.startswith(('Recurring alarm:', 'ALARM:', 'alert:'))
            and not is_anchor(labels)
            and 'handoff' not in labels
            and not title.startswith('ANCHOR'))


def active(row, owner):
    return (owner_name(row.get('assignee')) == owner_name(owner)
            and row.get('status') in ACTIVE
            and not _deferred_until_is_future(row.get('defer_until'))
            and real_work(row))


def rows(tracker, owner):
    """Only this owner's rows, complete across the configured stores."""
    from .files import FilesTracker
    from .beads import BeadsTracker, _bd_failure
    scoped = getattr(tracker, 'capacity_rows', None)
    if callable(scoped):
        found = scoped(owner).exact()
        if any(not isinstance(row, dict) or not row.get('assignee')
               or owner_name(row['assignee']) != owner_name(owner) for row in found):
            raise ValueError('owner scope returned ambiguous ownership')
        return found
    if isinstance(tracker, FilesTracker):
        return [json.loads(p.read_text()) | asdict(tracker._read(p, p.stem))
                for p in tracker.root.glob('*.json')]
    if isinstance(tracker, BeadsTracker):
        found = {}
        for repo in tracker.repos or [None]:
            for name in dict.fromkeys((owner, owner_name(owner))):
                run = tracker._bd if repo == tracker.repo else lambda *args: tracker._bd_in(repo, *args)
                result = run('list', '--assignee', name, '--json', '--limit', '0')
                if result.returncode:
                    raise _bd_failure('plate capacity', result, tool=tracker._tool)
                payload = json.loads(result.stdout)
                values = payload.get('issues') if isinstance(payload, dict) else payload
                if not isinstance(values, list) or (isinstance(payload, dict) and
                        (payload.get('has_more') or payload.get('truncated'))):
                    raise ValueError('owner listing completeness unproven')
                for row in values:
                    if not isinstance(row, dict) or not row.get('id'):
                        raise ValueError('invalid owner assignment row')
                    found[repo, row['id']] = row
        return list(found.values())
    raise ValueError('tracker has no complete owner assignment reader')


def size(tracker, owner):
    try:
        seen = rows(tracker, owner)
        for row in seen:
            if owner_name(row.get('assignee')) == owner_name(owner):
                if (not isinstance(row.get('id'), str) or not row['id']
                        or not isinstance(row.get('title'), str)
                        or row.get('status') not in ACTIVE | {'closed', 'tombstone', 'deferred'}):
                    raise ValueError('owner assignment fields incomplete or unsupported')
        return sum(active(row, owner) for row in seen)
    except Exception as error:
        raise CapacityUnknown(f'{owner_name(owner)} plate size UNKNOWN: {error}') from error


def ensure_room(tracker, owner, item=None):
    if item is not None and not real_work(vars(item)):
        return
    # Resuming one's own haul consumes no new slot, even on an older overfull plate.
    if item is not None and active(vars(item), owner):
        return
    count = size(tracker, owner)
    if count >= MAX_ACTIVE:
        raise PlateFull(f'{owner_name(owner)} plate full ({count}/{MAX_ACTIVE}); '
                        'new work stays unassigned in the pool')


def observed_size(tracker, owner):
    try:
        return size(tracker, owner)
    except CapacityUnknown:
        return None


_locks = threading.local()


@contextmanager
def assignment_lock(tracker, owner, *, dry_run=False):
    """Serialize cooperating writers on this host, including separate st processes.

    Remote hosts still need an atomic backend admission contract. This lock does
    not claim to serialize writers on another host or direct tracker commands.
    """
    if dry_run:
        yield
        return
    # Owner-global locally: different commands/cwds/backend wrappers must not
    # acquire different locks for the same worker on the same board.
    key = hashlib.sha256(owner_name(owner).encode()).hexdigest()
    held = getattr(_locks, 'held', set())
    if key in held:
        yield
        return
    folder = Path.home() / '.local/state/shantytown/plate-capacity'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / (key + '.lock')).open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        _locks.held = held | {key}
        try:
            yield
        finally:
            _locks.held = held
            fcntl.flock(handle, fcntl.LOCK_UN)


def serialized_dispatch(method):
    @wraps(method)
    def guarded(self, item_id, agent_name, *args, **kwargs):
        dry_run = kwargs.get('dry_run', args[0] if args else False)
        with assignment_lock(self.tracker, agent_name, dry_run=dry_run):
            return method(self, item_id, agent_name, *args, **kwargs)
    return guarded


def guard_producers(tracker, notify):
    """Guard every create/update producer using this tracker instance.

    Keep the real backend object (and its isinstance/read contracts). Full new
    work is retained in the pool; existing ownership is never stolen. Notification
    failure is reported after the mutation and must never trigger a create retry.
    This host lock serializes cooperating producers, not arbitrary remote SDKs.
    """
    if getattr(tracker, '_capacity_guarded', False):
        return tracker
    create, update = tracker.create, tracker.update

    def inform(owner, item_id):
        try:
            notify(owner, item_id)
        except Exception as error:
            import warnings
            warnings.warn(f'capacity: {item_id} retained in pool; lead notice UNKNOWN: {type(error).__name__}')

    def create_guarded(title, **fields):
        owner = fields.get('assignee')
        if not owner or not active({'status':'open'} | fields | {'title':title}, owner):
            return create(title, **fields)
        with assignment_lock(tracker, owner):
            full = False
            try:
                ensure_room(tracker, owner)
            except PlateFull:
                fields['assignee'] = None
                full = True
            item = create(title, **fields)  # exactly one write; UNKNOWN propagates
            if full:
                inform(owner, item.id)
            return item

    def update_guarded(item_id, **fields):
        if not any(k in fields for k in ('assignee', 'status')):
            return update(item_id, **fields)
        previous = tracker.get(item_id)
        owner = fields.get('assignee', previous.assignee)
        if not owner:
            return update(item_id, **fields)
        with assignment_lock(tracker, owner):
            current = tracker.get(item_id)
            if 'assignee' not in fields and current.assignee != previous.assignee:
                raise CapacityUnknown('owner changed before producer admission')
            if active(vars(current) | fields, owner):
                try:
                    ensure_room(tracker, owner, current)
                except PlateFull:
                    # Do not move somebody else's work to the pool or another owner.
                    if current.assignee:
                        raise
                    fields['assignee'] = ''
                    fields['status'] = 'open'
                    update(item_id, **fields)
                    inform(owner, item_id)
                    return
            return update(item_id, **fields)

    tracker.create, tracker.update = create_guarded, update_guarded
    tracker._capacity_guarded = True
    return tracker
