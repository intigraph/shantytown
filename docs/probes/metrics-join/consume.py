# /// script
# requires-python = ">=3.11"
# dependencies = ["duckdb==1.4.3"]
# ///
"""Join frozen daily-cost and scoped retained-close projections, without I/O SQL."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import duckdb


def load(path):
    with Path(path).open('rb') as handle:
        body = handle.read(16 * 1024 * 1024 + 1)
    if len(body) > 16 * 1024 * 1024:
        raise ValueError('projection exceeds byte budget')
    return json.loads(body), hashlib.sha256(body).hexdigest()


def join(daily, closed, identities, end):
    """No input claims full usage-day coverage; source census remains separate."""
    until = date.fromisoformat(end)
    if until > datetime.now(timezone.utc).date():
        raise ValueError('window must contain only complete UTC days')
    start = until - timedelta(days=30)
    if identities.get('schema_version') != 1:
        raise ValueError('unknown identity schema')
    agents = identities.get('agents')
    if not isinstance(agents, list) or not 1 <= len(agents) <= 128:
        raise ValueError('identity row budget')
    labels = [r['label'] for r in agents]
    iris = [r['iri'] for r in agents]
    if len(set(labels)) != len(labels) or len(set(iris)) != len(iris):
        raise ValueError('identity mapping must be one-to-one')
    if any(not isinstance(v, str) or not v for v in labels + iris):
        raise ValueError('empty identity')
    if any(not v.startswith(('https://', 'urn:')) for v in iris):
        raise ValueError('canonical identity must be an explicit IRI')
    if daily.get('schema_version') != 1 or daily.get('semantics') != 'event_day_usage':
        raise ValueError('requires request-day projection, never a corrective gauge')
    sessions = daily.get('sessions')
    if not isinstance(sessions, list) or len(sessions) > 4096:
        raise ValueError('daily source budget')
    usage, seen, capture_times = [], set(), []
    for snapshot in sessions:
        source = snapshot['source']
        identity = (source['harness'], source['session'])
        if identity in seen:
            raise ValueError('duplicate source session')
        seen.add(identity)
        captured = snapshot['captured_at']
        if type(captured) not in (int, float) or not 0 < captured <= datetime.now(timezone.utc).timestamp():
            raise ValueError('invalid source capture time')
        capture_times.append(captured)
        if not isinstance(snapshot.get('receipt'), str) or not snapshot['receipt']:
            raise ValueError('missing source receipt')
        row_keys = set()
        for row in snapshot['rows']:
            if row['agent'] != source['agent'] or row['harness'] != source['harness'] or row['agent'] not in labels:
                raise ValueError('unmapped or conflicting source identity')
            day = date.fromisoformat(row['day'])
            if day > datetime.fromtimestamp(captured, timezone.utc).date():
                raise ValueError('usage postdates capture')
            key = (row['day'], row['rig'], row['seed'], row['model'])
            if key in row_keys:
                raise ValueError('duplicate source/day/seed/model')
            row_keys.add(key)
            if not start <= day < until:
                continue
            counts = row['counts']
            if set(counts) != {'input_uncached', 'cache_read_input', 'cache_write_input', 'output'}:
                raise ValueError('unknown token breakdown')
            for kind, value in counts.items():
                if value is not None and (type(value) is not int or not 0 <= value <= 9223372036854775807):
                    raise ValueError('invalid token value')
                usage.append((row['agent'], day, kind, value))
    if len(usage) > 100_000:
        raise ValueError('usage row budget')
    if closed.get('schema_version') != 1 or closed.get('semantics') != 'retained_close_current_assignee':
        raise ValueError('unknown close projection semantics')
    if closed.get('start') != str(start) or closed.get('end_exclusive') != str(until):
        raise ValueError('close projection window mismatch')
    if closed.get('truncated') is not False or closed.get('graph_visible') is not True:
        raise ValueError('close projection visibility/integrity UNKNOWN')
    provenance = closed.get('source')
    if not isinstance(provenance, dict) or not str(provenance.get('graph_iri', '')).startswith(('https://', 'urn:')):
        raise ValueError('missing scoped graph provenance')
    digest = provenance.get('query_sha256', '')
    if not isinstance(digest, str) or len(digest) != 64 or any(v not in '0123456789abcdef' for v in digest):
        raise ValueError('missing graph query revision')
    captured = datetime.fromisoformat(provenance['captured_at'].replace('Z', '+00:00'))
    if captured.tzinfo is None or captured.timestamp() > datetime.now(timezone.utc).timestamp():
        raise ValueError('invalid graph capture time')
    closures, items = [], set()
    rows = closed.get('rows')
    if not isinstance(rows, list) or len(rows) > 100_000 or closed.get('distinct_control') != len(rows):
        raise ValueError('close projection control mismatch')
    for row in rows:
        item = row['item_iri']
        stamp = datetime.fromisoformat(row['closed_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None or not isinstance(item, str) or not item.startswith(('https://', 'urn:')):
            raise ValueError('invalid close identity/timestamp')
        day = stamp.astimezone(timezone.utc).date()
        if item in items or row['agent_iri'] not in iris or not start <= day < until:
            raise ValueError('duplicate, unmapped or out-of-window close')
        items.add(item)
        closures.append((item, row['agent_iri'], day))
    sql = Path(__file__).with_name('consume.sql').read_text()
    conn = duckdb.connect(':memory:', config={'threads': '1', 'memory_limit': '64MB',
        'enable_external_access': 'false', 'allow_unsigned_extensions': 'false', 'autoinstall_known_extensions': 'false',
        'autoload_known_extensions': 'false'})
    try:
        conn.execute('CREATE TABLE agents(label VARCHAR, iri VARCHAR)')
        conn.executemany('INSERT INTO agents VALUES (?,?)', list(zip(labels, iris)))
        conn.execute('CREATE TABLE days(day DATE)')
        conn.executemany('INSERT INTO days VALUES (?)', [(start + timedelta(days=n),) for n in range(30)])
        conn.execute('CREATE TABLE usage(agent VARCHAR, day DATE, kind VARCHAR, value BIGINT)')
        if usage:
            conn.executemany('INSERT INTO usage VALUES (?,?,?,?)', usage)
        conn.execute('CREATE TABLE closes(item_iri VARCHAR, agent_iri VARCHAR, day DATE)')
        if closures:
            conn.executemany('INSERT INTO closes VALUES (?,?,?)', closures)
        cur = conn.execute(sql)
        keys = [v[0] for v in cur.description]
        result = [dict(zip(keys, row)) for row in cur.fetchall()]
    finally:
        conn.close()
    return {'scope': 'supplied frozen sources; usage-day completeness UNKNOWN pending independent census',
        'window': [str(start), str(until)], 'engine': duckdb.__version__,
        'sql_sha256': hashlib.sha256(sql.encode()).hexdigest(),
        'usage_capture_times': sorted(set(capture_times)), 'closed_source': provenance, 'rows': result}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--daily', required=True)
    parser.add_argument('--closed', required=True)
    parser.add_argument('--identities', required=True)
    parser.add_argument('--end-exclusive', required=True)
    args = parser.parse_args()
    sources = {name: load(getattr(args, name)) for name in ('daily', 'closed', 'identities')}
    answer = join(*(sources[n][0] for n in ('daily', 'closed', 'identities')), args.end_exclusive)
    answer['input_sha256'] = {name: value[1] for name, value in sources.items()}
    print(json.dumps(answer, indent=2))
