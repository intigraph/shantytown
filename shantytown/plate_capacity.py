"""Bounded assignment admission; a partial plate is never spare capacity."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import fcntl
from functools import wraps
import hashlib
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from .inbox import is_anchor, is_message, _deferred_until_is_future
from .ask_visibility import is_ask, label_names

MAX_ACTIVE = 10
ACTIVE = frozenset({'open', 'hooked', 'in_progress', 'blocked'})


class CapacityUnknown(ValueError):
    pass


class PlateFull(ValueError):
    pass


def owner_name(owner):
    return (owner or '').strip().rstrip('/').rsplit('/', 1)[-1]


def real_work(row):
    """Count work the holder can perform, excluding delivery and human decisions.

    Match the producers' explicit labels and legacy title prefixes. A bug filed
    to repair an alarm remains work unless it carries a detector record marker.
    """
    title = (row.get('title') or '').lstrip()
    labels = label_names(row.get('labels'))
    return (not is_message(title)
            and not is_ask(row)
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


def rows(tracker, owner, *, admission=False):
    """Only this owner's rows, complete across the configured stores."""
    from .files import FilesTracker
    from .beads import BeadsTracker, _bd_failure
    scoped = (getattr(tracker, 'capacity_admission_rows', None) if admission else None)
    scoped = scoped or getattr(tracker, 'capacity_rows', None)
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


def counted_rows(tracker, owner, *, admission=False):
    try:
        seen = rows(tracker, owner, admission=admission)
        for row in seen:
            if owner_name(row.get('assignee')) == owner_name(owner):
                if (not isinstance(row.get('id'), str) or not row['id']
                        or not isinstance(row.get('title'), str)
                        or row.get('status') not in ACTIVE | {'closed', 'tombstone', 'deferred'}):
                    raise ValueError('owner assignment fields incomplete or unsupported')
        return [row for row in seen if active(row, owner)]
    except Exception as error:
        raise CapacityUnknown(f'{owner_name(owner)} plate size UNKNOWN: {error}') from error


def size(tracker, owner):
    return len(counted_rows(tracker, owner))


def _record_overflow(owner, candidate, counted):
    """Write ahead of a possible mutation, never claim it committed.

    Pure plans and dry runs hold no assignment lock and write nothing. Nested
    producer guards share the outer decision. A failed journal blocks the write;
    a later backend timeout leaves an admission record, not a success receipt.
    """
    owner = owner_name(owner)
    if hashlib.sha256(owner.encode()).hexdigest() not in getattr(_locks, 'held', set()):
        return
    identifiers = sorted(row['id'] for row in counted)
    key = (owner, candidate.get('id'), tuple(identifiers))
    recorded = _locks.overflow_recorded
    if key in recorded:
        return
    path = Path.home() / '.local/state/shantytown/plate-capacity/overflow.jsonl'
    event = dict(event='overflow_admission', owner=owner, item=candidate.get('id'),
                 title=candidate.get('title'),
                 priority=0, count=len(counted), cap=MAX_ACTIVE, counted_ids=identifiers,
                 at=datetime.now(timezone.utc).isoformat(), mutation_outcome='not_observed')
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            length = os.fstat(fd).st_size
            if length and os.pread(fd, 1, length - 1) != b'\n':
                raise OSError('incomplete overflow journal; preserve and reconcile it')
            handle.write(json.dumps(event, sort_keys=True) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise CapacityUnknown(f'P0 overflow journal unavailable; no assignment attempted: {error}') from error
    recorded.add(key)
    print(f'capacity overflow: {owner} {len(counted)}/{MAX_ACTIVE}; '
          f'item={candidate.get("id") or "new"}; counted_ids={",".join(identifiers)}; '
          f'admission recorded at {path} (not a mutation receipt)', file=sys.stderr)


def ensure_room(tracker, owner, item=None, *, candidate=None):
    prospective = candidate if candidate is not None else (vars(item) if item is not None else {})
    if prospective and not real_work(prospective):
        return
    # Resuming one's own haul consumes no new slot, even on an older overfull plate.
    if item is not None and active(vars(item), owner):
        return
    counted = counted_rows(tracker, owner, admission=True)
    count = len(counted)
    if count >= MAX_ACTIVE:
        # Blockers inherit priority 0 through the existing verified technical
        # dependency path. A label or an unknown/Boolean priority is no proof.
        if type(prospective.get('priority')) is int and prospective['priority'] == 0:
            _record_overflow(owner, prospective, counted)
            return
        identifiers = ','.join(sorted(row['id'] for row in counted))
        raise PlateFull(f'{owner_name(owner)} plate full ({count}/{MAX_ACTIVE}); '
                        f'counted_ids=[{identifiers}]; '
                        'new work stays unassigned in the pool')


def observed_size(tracker, owner):
    try:
        return size(tracker, owner)
    except CapacityUnknown:
        return None


def ensure_update_room(tracker, owner, current, candidate):
    """Admission follows slot membership, including delivery-to-work changes."""
    if active(candidate, owner) and not active(vars(current), owner):
        ensure_room(tracker, owner, current, candidate=candidate)


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
        previous_records = getattr(_locks, 'overflow_recorded', set())
        _locks.overflow_recorded = set()
        try:
            yield
        finally:
            _locks.overflow_recorded = previous_records
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
        fields = {k: v for k, v in fields.items() if v is not None}
        owner = fields.get('assignee')
        if not owner or not active({'status':'open'} | fields | {'title':title}, owner):
            return create(title, **fields)
        with assignment_lock(tracker, owner):
            full = False
            try:
                ensure_room(tracker, owner, candidate={'status': 'open', 'title': title} | fields)
            except PlateFull:
                fields['assignee'] = None
                full = True
            item = create(title, **fields)  # exactly one write; UNKNOWN propagates
            if full:
                inform(owner, item.id)
            return item

    def update_guarded(item_id, **fields):
        # Backends ignore None, while an empty value explicitly clears a field.
        proposed = {k: v for k, v in fields.items() if v is not None}
        if not any(k in proposed for k in ('assignee', 'status', 'title', 'labels', 'defer_until')):
            return update(item_id, **fields)
        previous = tracker.get(item_id)
        owner = proposed.get('assignee', previous.assignee)
        if not owner:
            return update(item_id, **fields)
        with assignment_lock(tracker, owner):
            current = tracker.get(item_id)
            if 'assignee' not in proposed and current.assignee != previous.assignee:
                raise CapacityUnknown('owner changed before producer admission')
            if active(vars(current) | proposed, owner):
                try:
                    ensure_update_room(tracker, owner, current, vars(current) | proposed)
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
