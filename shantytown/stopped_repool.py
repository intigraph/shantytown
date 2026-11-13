"""Priority-aged stopped-owner repooling in the existing fleet tend pass.

# arming: library; existing fleet tend schedule, never run as a backfill.
"""
from contextlib import nullcontext
import json
import math
from pathlib import Path
import time

from .ask_visibility import is_ask
from .files import write_json_atomic
from .inbox import is_message
from .stranded_work import eligible, owner


def candidates(rows, evidence, now):
    result = []
    urgent = {owner(row) for row in rows
              if row.get('status') in {'open', 'in_progress'}
              and not is_message(row.get('title', '')) and not is_ask(row)
              and type(row.get('priority')) is int and row['priority'] <= 1}
    for row in rows:
        name = owner(row)
        observed = evidence.get(name, {})
        since = observed.get('since')
        if (row.get('status') not in {'open', 'in_progress'} or not eligible(row)
                or is_ask(row) or observed.get('state') not in {'stopped', 'held', 'down'}
                or type(since) not in (int, float) or not math.isfinite(since)
                or since < 0 or since > now):
            continue
        threshold = 1800 if name in urgent else 14400
        if now - since >= threshold:
            result.append(row)
    return sorted(result, key=lambda r: (r['priority'], r['id']))


def repool(rows, evidence, *, read, release, observe, fence, journal,
           save, now, dry_run=False, limit=40):
    """CAS release with comment, lifecycle recheck and durable uncertain intents."""
    if len(rows) > 5000 or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('stopped-owner work census incomplete or exceeds bound')
    findings = []
    for row in rows:
        if (is_message(row.get('title', ''))
                and evidence.get(owner(row), {}).get('state') in {'stopped', 'held', 'down'}):
            findings.append((row['id'], 'inbox pointer to unavailable owner; not delivered work'))
    deadline = time.monotonic() + 5
    for row in candidates(rows, evidence, now)[:limit]:
        if time.monotonic() >= deadline:
            findings.append((row['id'], 'pass budget exhausted; untouched'))
            break
        identity, name = row['id'], owner(row)
        if identity in journal:
            # Never repeat an uncertain write. Exact read can prove completion.
            current = read(identity)
            old = journal[identity]
            comments = current.get('comments') or []
            done = (not owner(current) and current.get('status') == 'open'
                    and any(c.get('text') == old['comment'] for c in comments))
            findings.append((identity, 'reconciled' if done else 'outcome UNKNOWN; no retry'))
            continue
        if dry_run:
            findings.append((identity, f'would repool from {name} to open/unassigned'))
            continue
        with fence(name):
            current = read(identity)
            fresh = observe(name)
            if (fresh != evidence[name] or owner(current) != name
                    or current.get('status') != row['status']
                    or not candidates([current], {name: fresh}, now)):
                findings.append((identity, 'changed evidence; untouched'))
                continue
            comment = f'st fleet tend: repooled from stopped holder {name}; {fresh["state"]} since {fresh["since"]}. Original notes and workspace retained.'
            journal[identity] = {'comment': comment, 'revision': current.get('revision')}
            save(journal)  # Persist BEFORE the remote side effect.
            outcome = release(current, comment, operator_stopped=True)
            findings.append((identity, outcome))  # Adapter verifies fields AND comment.
    return findings


def sweep(root, registry, tracker, panes, *, dry_run=False, now=None):
    from .agent_hold import store as hold_store
    from .cycle import lifecycle_lock
    from .deployment import local_host
    from .stopped import FilesStops
    import fcntl
    now = time.time() if now is None else now
    root = Path(root)
    cards = registry.all().exact()
    host = local_host(root)
    if not host:
        raise ValueError('stopped-owner host scope UNKNOWN')
    if len(cards) > 100 or len({c.name for c in cards}) != len(cards):
        raise ValueError('stopped-owner crew census incomplete or exceeds bound')
    local = {c.name: c for c in cards if c.host == host}
    folder = root / 'stopped-repool'
    state_path = folder / 'down.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    def observe(name, *, fresh=False):
        card = registry.get(name) if fresh else local[name]
        if card != local[name]:
            return {'state': 'unknown'}
        for kind, store in [('stopped', FilesStops(root/'stopped')), ('held', hold_store(root))]:
            record = store.get(name)
            if record:
                return {'state': kind, 'since': record.at}
            if (store.root / (name+'.json')).exists():
                return {'state': 'unknown'}
        actual = panes.owner_state(card.pane)
        if actual != 'down':
            return {'state': 'live' if actual == 'live' else 'unknown'}
        from .owned_work import OwnedWork
        generation = OwnedWork(root).snapshot().get(name, {}).get('generation', '')
        previous = state.get(name, {})
        if not isinstance(previous, dict) or previous.get('generation') != generation:
            previous = {'since': now, 'generation': generation}
            state[name] = previous
        return {'state': 'down', **previous}
    # Dry run never creates a directory, lock, observation or remote write.
    if not dry_run:
        folder.mkdir(parents=True, exist_ok=True)
    lock = nullcontext() if dry_run else (folder/'lock').open('a')
    with lock as handle:
        if handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        evidence = {name: observe(name) for name in local}
        for name in list(state):
            if evidence.get(name, {}).get('state') != 'down':
                state.pop(name)
        if not dry_run:
            write_json_atomic(state_path, state)
        unavailable = [n for n, e in evidence.items() if e.get('state') in {'stopped', 'held', 'down'}]
        if not unavailable:
            return []
        rows = tracker.stranded_rows(unavailable)
        path = folder/'intents.json'
        journal = json.loads(path.read_text()) if path.exists() else {}
        return repool(rows, evidence, read=tracker.stranded_read,
                      release=tracker.release_stranded, observe=lambda name: observe(name, fresh=True),
                      fence=lambda name: lifecycle_lock(root, name), journal=journal,
                      save=lambda value: write_json_atomic(path, value), now=now, dry_run=dry_run)
