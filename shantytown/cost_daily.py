"""Disposable UTC-day projection of Camayoc's parsed request evidence.

No harness parser, quota sampler or token arithmetic is duplicated here. The
cost producer holds its existing lock while replacing a session's projection;
replaying or correcting a session never adds its old allocation a second time.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import os

KINDS = ('input_uncached', 'cache_read_input', 'cache_write_input', 'output')


def project(result, *, now):
    if result.get('schema_version') != 1 or result.get('errors'):
        raise ValueError('daily cost requires a successful Camayoc request projection')
    records = result.get('records')
    if not isinstance(records, list) or not records or len(records) > 100_000:
        raise ValueError('daily request projection absent or exceeds row budget')
    cutoff = datetime.fromtimestamp(now, timezone.utc).date().toordinal() - 30
    requests, sessions, session_agents = {}, {}, {}
    for record in records:
        identity = tuple(record.get(k) for k in ('harness', 'session', 'agent', 'id'))
        if any(not isinstance(v, str) or not v for v in identity):
            raise ValueError('daily request identity missing')
        session_key = identity[:2]
        if session_key in session_agents and session_agents[session_key] != identity[2]:
            raise ValueError('ambiguous agent for source session')
        session_agents[session_key] = identity[2]
        prior = requests.get(identity)
        if prior is not None:
            if prior != record:
                raise ValueError('conflicting daily request identity')
            continue
        requests[identity] = record
        raw = record.get('at')
        if isinstance(raw, str):
            stamp = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('request timestamp requires timezone')
            stamp = stamp.astimezone(timezone.utc)
        elif type(raw) in (int, float):
            stamp = datetime.fromtimestamp(raw, timezone.utc)
        else:
            raise ValueError('request timestamp missing')
        if stamp.timestamp() > now:
            raise ValueError('request timestamp is in the future')
        counts = record.get('counts')
        if not isinstance(counts, dict) or set(counts) != set(KINDS):
            raise ValueError('daily token breakdown missing')
        if any(v is not None and (type(v) is not int or v < 0) for v in counts.values()):
            raise ValueError('invalid daily token quantity')
        dimensions = tuple(record.get(k) for k in ('rig', 'bead', 'agent', 'harness', 'model'))
        if any(not isinstance(v, str) or not v for v in dimensions[:4]):
            raise ValueError('daily attribution dimensions missing')
        if dimensions[4] is not None and not isinstance(dimensions[4], str):
            raise ValueError('invalid daily model')
        session = identity[:3]
        groups = sessions.setdefault(session, {})
        if stamp.date().toordinal() < cutoff:
            continue
        key = (stamp.date().isoformat(), *dimensions)
        group = groups.setdefault(key, {'counts': dict.fromkeys(KINDS, 0), 'requests': 0,
                                       'attribution_known': True})
        group['requests'] += 1
        group['attribution_known'] &= record.get('attribution') == 'attributed'
        for kind, value in counts.items():
            if value is None:
                group['counts'][kind] = None
            elif group['counts'][kind] is not None:
                group['counts'][kind] += value
    projected = []
    for session, groups in sorted(sessions.items()):
        rows = []
        for key, value in sorted(groups.items(), key=lambda x: tuple(str(v) for v in x[0])):
            rows.append(dict(zip(('day', 'rig', 'seed', 'agent', 'harness', 'model'), key)) | value)
        projected.append({'source': dict(zip(('harness', 'session', 'agent'), session)),
                          'receipt': result.get('receipt'), 'captured_at': now, 'rows': rows})
    return projected


def update(path, result, *, now):
    """Caller holds the cost lock. Validate before touching the last good file."""
    fresh = project(result, now=now)
    destination = Path(path)
    old = json.loads(destination.read_text()) if destination.exists() else {'schema_version': 1, 'sessions': []}
    if old.get('schema_version') != 1 or not isinstance(old.get('sessions'), list):
        raise ValueError('unknown daily cost cache schema')
    by_source = {}
    agents_by_session = {}
    for snapshot in old['sessions']:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('source'), dict) or not isinstance(snapshot.get('rows'), list):
            raise ValueError('malformed daily session cache')
        source = snapshot['source']
        key = tuple(source[k] for k in ('harness', 'session', 'agent'))
        if key in by_source:
            raise ValueError('duplicate cached source')
        if key[:2] in agents_by_session and agents_by_session[key[:2]] != key[2]:
            raise ValueError('ambiguous cached session agent')
        agents_by_session[key[:2]] = key[2]
        by_source[key] = snapshot
    for snapshot in fresh:
        key = tuple(snapshot['source'][k] for k in ('harness', 'session', 'agent'))
        if key[:2] in agents_by_session and agents_by_session[key[:2]] != key[2]:
            raise ValueError('source session agent changed without a reviewed mapping')
        if key in by_source and by_source[key]['captured_at'] > now:
            raise ValueError('daily source observation moved backwards')
        by_source[key] = snapshot
    cutoff = datetime.fromtimestamp(now, timezone.utc).date().toordinal() - 30
    retained = []
    for _, snapshot in sorted(by_source.items()):
        rows = [r for r in snapshot['rows'] if datetime.fromisoformat(r['day']).date().toordinal() >= cutoff]
        if rows:
            retained.append({**snapshot, 'rows': rows})
    if len(retained) > 4096 or sum(len(s['rows']) for s in retained) > 100_000:
        raise ValueError('daily cache budget exceeded')
    payload = {'schema_version': 1, 'semantics': 'event_day_usage',
               'scope': 'supplied Camayoc transcript requests; not complete agent-day history',
               'day_coverage': 'UNKNOWN until independent source census',
               'generated_at': now, 'sessions': retained}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=destination.parent, delete=False) as handle:
            temporary = handle.name
            json.dump(payload, handle, sort_keys=True)
            handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return payload
