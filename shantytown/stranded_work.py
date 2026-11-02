"""Confirmed stopped owners, persistent attention and revision-fenced release.

# arming: library; opt-in existing fleet-tend sweep, never a second timer.

Lease expiry is not process death. Callers supply a complete board/card census
and checked process evidence. Release is separately admitted, off by default.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
import math
from pathlib import Path
import time

from .files import write_json_atomic
from .inbox import is_message
from .owned_work import _agent, _time

T1 = 2 * 3600
T2 = 24 * 3600


def owner(row):
    return (row.get('assignee') or '').rsplit('/', 1)[-1]


def eligible(row):
    """Malformed parking metadata refuses release rather than ending a hold."""
    labels = row.get('labels') or []
    if not isinstance(labels, list):
        return False
    return (row.get('status') in {'open', 'in_progress'}
            and bool(owner(row)) and not is_message(row.get('title', ''))
            and not row.get('title', '').lstrip().upper().startswith('ASK ')
            and not row.get('defer_until') and not row.get('blocker_kind')
            and not any(str(label).startswith(('blocked:', 'deferred', 'parked'))
                        or label in {'inbox', 'needs-stiwi', 'desk', 'decision-needed'}
                        for label in labels)
            and type(row.get('priority')) is int and row['priority'] in range(5))


def resume_exempt(value, now):
    if value is None:
        return False
    # Unknown/malformed intent is a hold, never permission to pool work.
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp.tzinfo is None or stamp.timestamp() > now
    except (ValueError, TypeError, AttributeError):
        return True


class StrandedWork:
    def __init__(self, root):
        self.root = Path(root) / 'stranded-work'

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / 'lock').open('a') as lock:
            # Another tend pass may be in a remote write: skip, never queue it.
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            path = self.root / 'attention.json'
            data = json.loads(path.read_text()) if path.exists() else {}
            yield data
            write_json_atomic(path, data)

    def snapshot(self):
        path = self.root / 'attention.json'
        return json.loads(path.read_text()) if path.exists() else {}

    def tick(self, rows, cards, *, observe, recipient, notify, read, release,
             checkpoint, fence, now=None, release_admitted=False, t1=T1, t2=T2,
             budget=5, max_intents=4, clock=time.monotonic):
        """One complete, bounded snapshot; no retries or ownership guesses.

        read/release are revision-aware adapter seams, NOT generic update.
        notify uses the existing keyed inbox. A pending/unknown remote intent
        is never submitted again, even if this process died before its reply.
        """
        now = _time(time.time() if now is None else now)
        if any(not math.isfinite(v) or v < 0 for v in (t1, t2)) or t2 < t1:
            raise ValueError('invalid stranded-owner deadlines')
        if not math.isfinite(budget) or not 0 < budget <= 30 or type(max_intents) is not int or not 0 < max_intents <= 4:
            raise ValueError('invalid stranded-owner pass bounds')
        deadline, intents = clock() + budget, 0
        if len(rows) > 5000 or len(cards) > 100:
            raise ValueError('stranded-owner census exceeds bounds')
        if len({r['id'] for r in rows}) != len(rows):
            raise ValueError('duplicate work identities')
        seen = {r['id']: r for r in rows}
        active = {identity: r for identity, r in seen.items() if eligible(r)}
        observations = {}
        result = []
        with self.locked() as data:
            def save():
                write_json_atomic(self.root / 'attention.json', data)
            for identity, previous in data.items():
                if identity not in active:
                    row = seen.get(identity)
                    # A complete active/deferred projection can prove removal
                    # from scope. Malformed priority/labels cannot prove it.
                    if row is not None and (type(row.get('priority')) is not int
                            or not isinstance(row.get('labels') or [], list)):
                        previous.update(evidence='UNKNOWN', checked_at=now)
                    else:
                        previous.update(active=False, resolved_at=now)
            ordered = sorted(active.items(), key=lambda pair:
                (data.get(pair[0], {}).get('checked_at', -1), pair[0]))
            for identity, row in ordered:
                if clock() >= deadline:
                    result.append((identity, 'pass budget exhausted; remaining evidence unchanged'))
                    break
                name = _agent(owner(row))
                if name not in observations:
                    observations[name] = observe(name, cards.get(name))
                observation = observations[name]
                state = observation.get('state')
                if state not in {'live', 'down', 'missing', 'unknown'}:
                    raise ValueError('invalid owner observation')
                previous = data.get(identity, {})
                if previous and previous.get('owner') != name:
                    previous.update(active=False, resolved_at=now)
                if (state == 'live' or resume_exempt(observation.get('resume_at'), now)):
                    if previous:
                        previous.update(active=False, resolved_at=now)
                    continue
                if state == 'unknown':
                    if previous:
                        previous.update(evidence='UNKNOWN', checked_at=now)
                    result.append((identity, 'owner liveness UNKNOWN'))
                    continue
                generation = observation.get('generation')
                if not isinstance(generation, str) or not generation:
                    raise ValueError('owner generation unproven')
                same = (previous.get('owner') == name
                        and previous.get('generation') == generation
                        and previous.get('active') and previous.get('evidence') != 'UNKNOWN')
                if not same:
                    if previous:
                        archive = hashlib.sha256(json.dumps(previous, sort_keys=True).encode()).hexdigest()
                        write_json_atomic(self.root / (archive + '.json'), previous)
                    # First confirmed absence starts the clock. Item age and
                    # expired heartbeat are not a manufactured down-since.
                    previous = dict(owner=name, generation=generation, down_since=now,
                                    active=True, item=identity, notice='pending')
                    data[identity] = previous
                previous.update(checked_at=now, evidence=state)
                age = now - previous['down_since']
                urgent = row['priority'] == 0
                previous['attention'] = urgent or state == 'missing' or age >= t1
                previous['release_due'] = urgent or age >= t2
                if not previous['attention']:
                    continue
                key = hashlib.sha256(json.dumps([identity, name, generation,
                      previous['down_since']], separators=(',', ':')).encode()).hexdigest()
                marker = 'stranded-owner:' + key
                previous['marker'] = marker
                save()  # Attention survives even a refused/unknown lead route.
                if previous['notice'] == 'pending':
                    if intents >= max_intents or clock() >= deadline:
                        result.append((identity, 'attention retained; intent budget exhausted'))
                        continue
                    destination = recipient(name, cards)
                    body = (f'ERROR {marker} {identity}: owner {name} {state}; '
                            f'down since {previous["down_since"]}. Persistent attention '
                            f'{self.root / "attention.json"}; checkpoint/trees retained.')
                    if len(body.encode()) > 480:
                        raise ValueError('stranded-owner pointer exceeds inbox bound')
                    previous.update(notice='attempting', recipient=destination)
                    save()
                    intents += 1
                    try:
                        notify(destination, body, marker)
                        previous['notice'] = 'delivered'
                    except Exception:
                        previous['notice'] = 'unknown'
                    save()
                result.append((identity, 'needs attention'))
                if not release_admitted or not previous['release_due']:
                    continue
                if previous['notice'] != 'delivered':
                    result.append((identity, 'error delivery UNKNOWN; no release'))
                    continue
                if previous.get('release') in {'attempting', 'unknown', 'released'}:
                    result.append((identity, 'release ' + previous['release'] + '; read-back only'))
                    continue
                if self.unresolved_release(name):
                    result.append((identity, 'earlier release UNKNOWN; no new intent'))
                    continue
                if intents >= max_intents or clock() >= deadline:
                    result.append((identity, 'release due; pass budget exhausted'))
                    continue
                # The sanctioned launch/stop paths share this lock. Recheck
                # after checkpoint I/O; item CAS fences assignment/parking races.
                with fence(name):
                    preserved = checkpoint(name, cards.get(name))
                    if (not isinstance(preserved, dict)
                            or not all(isinstance(preserved.get(k), str) and preserved[k]
                                       for k in ('worktree', 'branch', 'checkpoint'))):
                        result.append((identity, 'checkpoint preservation UNKNOWN'))
                        continue
                    current = read(identity)
                    fresh = observe(name, cards.get(name))
                    if (fresh != observation or not eligible(current)
                            or owner(current) != name or current['priority'] != row['priority']):
                        result.append((identity, 'changed evidence; no release'))
                        continue
                    comment = json.dumps(dict(marker=marker, original_owner=current['assignee'],
                        down_since=previous['down_since'], **preserved), sort_keys=True)
                    previous.update(release='attempting', preserved=preserved,
                                    attempted_revision=current.get('revision'))
                    save()
                    journal_path = self.root / 'release-intents.json'
                    journal = json.loads(journal_path.read_text()) if journal_path.exists() else {}
                    journal[marker] = dict(owner=name, item=identity, outcome='attempting',
                                           revision=current.get('revision'), comment=comment)
                    write_json_atomic(journal_path, journal)
                    intents += 1
                    try:
                        outcome = release(current, comment)
                        if outcome not in {'released', 'conflict'}:
                            raise ValueError('release outcome unproven')
                        previous['release'] = outcome
                    except Exception:
                        previous['release'] = 'unknown'
                    journal[marker]['outcome'] = previous['release']
                    write_json_atomic(journal_path, journal)
                    save()
                    result.append((identity, 'release ' + previous['release']))
        return result

    def unresolved_release(self, name):
        """An uncertain server commit must be reconciled before a new launch."""
        path = self.root / 'release-intents.json'
        journal = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(journal, dict):
            raise ValueError('stranded release journal malformed')
        if any(entry.get('owner') == name and entry.get('outcome') in {'attempting', 'unknown'}
               for entry in journal.values()):
            return True
        states = self.snapshot()
        if not isinstance(states, dict):
            raise ValueError('stranded attention ledger malformed')
        return any(entry.get('owner') == name
                   and entry.get('release') in {'attempting', 'unknown'}
                   for entry in states.values())
