"""Non-item duties consumed by the existing stranded-owner sweep.

# arming: library; the existing opt-in stranded-owner-work tend pass.

Registry ownership is effective ONLY for consumers explicitly using this
registry. An external binding is never repaired by editing its description.
It gets one idempotently keyed repair item and a verified administrator page.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import time

from .files import write_json_atomic

KINDS = ('merge-queue', 'reviewer', 'scheduled-job', 'alert-keeper',
         'review-reservation', 'haul')
SCHEMA = 'shantytown.duties/1'
MAX_BYTES, MAX_ROWS = 1024 * 1024, 1000


def _routing(data):
    routing = data.get('routing')
    if not isinstance(routing, dict) or set(routing) != {'internal-landing'}:
        raise ValueError('internal landing routing unproven')
    rule = routing['internal-landing']
    if (not isinstance(rule, dict)
            or set(rule) != {'repository_prefix', 'holder_rule', 'require_live'}
            or not isinstance(rule['repository_prefix'], str)
            or not re.fullmatch(r'[A-Za-z0-9_.-]+/', rule['repository_prefix'])
            or rule['holder_rule'] != 'author' or rule['require_live'] is not True):
        raise ValueError('internal landing owner must remain the live author')
    return rule


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}', value):
        raise ValueError('invalid duty or holder identity')
    return value


def _read(path, *, expected_sha256=None):
    if path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise ValueError('unsafe or oversized duty data')
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError('oversized duty data')
    if expected_sha256 is not None:
        if (not isinstance(expected_sha256, str)
                or not re.fullmatch('[0-9a-f]{64}', expected_sha256)
                or hashlib.sha256(raw).hexdigest() != expected_sha256):
            raise ValueError('duty plan bytes differ from the reviewed digest')
    return json.loads(raw)


def validate(data):
    """Coverage is a declaration, never inferred from an empty partial list."""
    if (not isinstance(data, dict) or data.get('schema') != SCHEMA
            or type(data.get('revision')) is not int or data['revision'] < 1
            or data.get('coverage') != list(KINDS)
            or not isinstance(data.get('entries'), list)
            or len(data['entries']) > MAX_ROWS):
        raise ValueError('duty registry coverage/schema UNKNOWN')
    seen = set()
    if 'routing' in data:
        _routing(data)
    for row in data['entries']:
        ident = _name(row['id'])
        if ident in seen:
            raise ValueError('duplicate duty identity')
        seen.add(ident)
        _name(row['holder'])
        if (row.get('kind') not in KINDS or row.get('binding') not in {'registry', 'external'}
                or type(row.get('priority')) is not int or row['priority'] not in range(5)
                or not isinstance(row.get('source'), str) or not row['source']
                or len(row['source']) > 1024
                or not isinstance(row.get('candidates', []), list)
                or not isinstance(row.get('authors', []), list)):
            raise ValueError('invalid duty record')
        for name in row.get('candidates', []) + row.get('authors', []):
            _name(name)
    return data


class Duties:
    def __init__(self, root):
        self.root = Path(root) / 'duties'
        self.path = self.root / 'registry.json'

    def load(self):
        return validate(_read(self.path))

    def install(self, plan, *, expected_revision, apply=False):
        """Merge managed inventory without reverting supported live handoffs.

        Missing entries are retained: omission is not duty retirement. The
        deployment must verify external binding readback before updating its
        holder here. This method does not probe or change those consumers.
        """
        validate(plan)
        before = self.load() if self.path.exists() else None
        revision = before['revision'] if before else 0
        if revision != expected_revision:
            raise ValueError('duty inventory revision conflict')
        merged = {row['id']: deepcopy(row) for row in (before or {}).get('entries', [])}
        for row in plan['entries']:
            old = merged.get(row['id'])
            new = deepcopy(row)
            if old and old['binding'] == new['binding'] == 'registry':
                if (old['holder'] in new.get('candidates', [])
                        and old['holder'] not in new.get('authors', [])):
                    new['holder'] = old['holder']
            merged[row['id']] = new
        after = dict(schema=SCHEMA, revision=revision + 1,
                     coverage=list(KINDS),
                     routing=deepcopy(plan.get('routing', (before or {}).get('routing'))),
                     entries=sorted(merged.values(), key=lambda r: r['id']))
        validate(after)
        changed = (before is None or before.get('routing') != after['routing']
                   or sorted(before['entries'], key=lambda r: r['id']) != after['entries'])
        result = dict(revision=revision, changed=changed, duties=len(after['entries']))
        if apply and changed:
            with self.locked():
                current = self.load() if self.path.exists() else None
                if current != before:
                    raise ValueError('duty inventory changed; no install')
                write_json_atomic(self.path, after)
                if self.load() != after:
                    raise ValueError('duty inventory read-back UNKNOWN')
                result['revision'] = after['revision']
        return result

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lockpath = self.root / 'lock'
        if lockpath.is_symlink():
            raise ValueError('unsafe duty lock')
        with lockpath.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def _save_registry(self, before, after):
        # Installation and supported handoffs share this lock and revision.
        if self.load() != before:
            raise ValueError('duty registry changed; no handoff')
        after = deepcopy(after)
        after['revision'] += 1
        validate(after)
        write_json_atomic(self.path, after)
        if self.load() != after:
            raise ValueError('duty handoff read-back UNKNOWN')

    def handoff(self, ident, target, *, expected_revision, live):
        """Supported registry binding only; never rewrite external config."""
        with self.locked():
            before = self.load()
            if before['revision'] != expected_revision:
                raise ValueError('duty revision conflict')
            after = deepcopy(before)
            rows = [r for r in after['entries'] if r['id'] == ident]
            if len(rows) != 1:
                raise ValueError('unknown duty')
            row = rows[0]
            if (row['binding'] != 'registry' or target not in row.get('candidates', [])
                    or target in row.get('authors', []) or not live(target)):
                raise ValueError('unsupported or ineligible duty handoff')
            row['holder'] = target
            self._save_registry(before, after)

    def resolve(self, ident, *, live):
        rows = [r for r in self.load()['entries'] if r['id'] == ident]
        if (len(rows) != 1 or rows[0]['binding'] != 'registry'
                or rows[0]['holder'] in rows[0].get('authors', [])
                or not live(rows[0]['holder'])):
            raise ValueError('effective duty holder UNKNOWN or unavailable')
        return rows[0]['holder']

    def send_landing(self, repository, author, body, key, *, live, inbox):
        """Internal landing/main-watch goes to its live author, never a queue.

        A structured consumer calls this at delivery time. The duty lock is
        shared with permanent stop, so a cached target cannot outrun that stop.
        This sends no dispatch, wakes no process and grants no merge authority.
        """
        if (not isinstance(repository, str)
                or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository)):
            raise ValueError('unsupported internal landing repository')
        _name(author)
        if (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9:/_.-]{1,256}', key)
                or not isinstance(body, str) or not body):
            raise ValueError('invalid landing delivery identity or body')
        message = key + ' ' + body
        with self.locked():
            rule = _routing(self.load())
            if not repository.startswith(rule['repository_prefix']):
                raise ValueError('unsupported internal landing repository')
            if not live(author):
                raise ValueError('landing author is stopped or liveness UNKNOWN; no send')
            receipt = inbox.deliver_once(author, message, key, frm='st duty')
            seen = inbox.find_delivery(author, key)
            if seen is None or seen.id != receipt.id or seen.body != message:
                raise ValueError('landing delivery UNKNOWN; reconcile retained key')
            return receipt

    def tick(self, *, observe, live, administrator, ensure_issue, notify,
             now=None, release=False, max_actions=10):
        """One bounded pass, stable per-duty repair identity, no new scheduler."""
        now = time.time() if now is None else now
        if not math.isfinite(now) or now < 0 or not 1 <= max_actions <= 20:
            raise ValueError('invalid duty sweep bound')
        with self.locked():
            registry = self.load()
            statepath = self.root / 'attention.json'
            states = _read(statepath) if statepath.exists() else {}
            if not isinstance(states, dict) or len(states) > MAX_ROWS:
                raise ValueError('duty attention UNKNOWN')
            result, actions, observations = [], 0, {}
            report = dict(checked_at=now, complete=True,
                          orphaned={k: 0 for k in KINDS}, unknown=0)
            ordered = sorted(registry['entries'], key=lambda row: (
                bool(states.get(row['id'], {}).get('repair')
                     and states.get(row['id'], {}).get('paged')),
                states.get(row['id'], {}).get('checked_at', -1), row['id']))
            for row in ordered:
                ident, holder = row['id'], row['holder']
                if holder not in observations:
                    observations[holder] = observe(holder)
                evidence = observations[holder]
                previous = states.get(ident, {})
                if evidence.get('state') == 'live':
                    previous.update(active=False, checked_at=now)
                    states[ident] = previous
                    continue
                if evidence.get('state') not in {'operator-stopped', 'down', 'held', 'missing'}:
                    report['complete'] = False
                    report['unknown'] += 1
                    previous.update(evidence='UNKNOWN', checked_at=now)
                    states[ident] = previous
                    result.append((ident, 'duty owner liveness UNKNOWN'))
                    continue
                generation = evidence.get('generation')
                if not isinstance(generation, str) or not generation:
                    raise ValueError('duty owner generation UNKNOWN')
                same = (previous.get('holder') == holder
                        and previous.get('generation') == generation
                        and previous.get('active') is True
                        and previous.get('evidence') != 'UNKNOWN')
                if not same:
                    # Only the independently read operator-stop timestamp may
                    # predate this first measured absence. A lease never may.
                    since = evidence.get('stopped_at', now)
                    if not isinstance(since, (int, float)) or not 0 <= since <= now:
                        raise ValueError('duty stop clock UNKNOWN')
                    # A changed owner/stop generation cannot change an
                    # already transmitted intent under the same native key.
                    # Retain its exact payload and destination for recovery.
                    retained = {key: deepcopy(previous[key])
                                for key in ('intent', 'intent_target') if key in previous}
                    previous = dict(holder=holder, generation=generation, since=since,
                                    **retained)
                previous.update(active=True, evidence=evidence['state'], checked_at=now)
                states[ident] = previous
                threshold = 1800 if row['priority'] <= 1 else 14400
                if now - previous['since'] < threshold:
                    continue
                report['orphaned'][row['kind']] += 1
                result.append((ident, 'orphaned duty'))
                if not release or actions >= max_actions:
                    continue
                actions += 1
                candidates = [n for n in row.get('candidates', [])
                              if n != holder and n not in row.get('authors', []) and live(n)]
                if row['binding'] == 'registry' and candidates:
                    target = candidates[0]
                    fresh = observe(holder)
                    if fresh != evidence or not live(target):
                        result.append((ident, 'duty evidence changed; no handoff'))
                        continue
                    after = deepcopy(registry)
                    next(r for r in after['entries'] if r['id'] == ident)['holder'] = target
                    self._save_registry(registry, after)
                    registry = self.load()
                    previous.update(active=False, reassigned_to=target)
                    report['orphaned'][row['kind']] -= 1
                    result.append((ident, 'duty reassigned to ' + target))
                    continue
                # Stable across refirings and stopped-owner generations. The
                # backend must guarantee idempotent create for this identity.
                key = 'stranded-duty:' + hashlib.sha256(ident.encode()).hexdigest()
                if not previous.get('repair'):
                    target = previous.setdefault('intent_target', administrator())
                    if not live(target):
                        result.append((ident, 'administrator not live; no repair intent'))
                        continue
                    payload = previous.setdefault('intent', dict(
                        id=ident, kind=row['kind'], holder=holder, source=row['source']))
                    write_json_atomic(statepath, states)  # BEFORE remote intent.
                    try:
                        repair = ensure_issue(payload, target, key)
                        previous['repair'] = repair
                    except Exception:
                        previous['repair_state'] = 'UNKNOWN'
                        write_json_atomic(statepath, states)
                        result.append((ident, 'repair intent UNKNOWN; stable key retained'))
                        continue
                if not previous.get('paged'):
                    try:
                        target = administrator()
                        notify(target, f'{key} ERROR duty {ident}; '
                               f'repair {previous["repair"]}; binding needs its normal repair lane.', key)
                        previous['paged'] = True
                    except Exception:
                        result.append((ident, 'duty page UNKNOWN'))
                result.append((ident, 'repair ' + previous['repair']))
                write_json_atomic(statepath, states)
            write_json_atomic(statepath, states)
            write_json_atomic(self.root / 'report.json', report)
            return result


def summary(root, *, now=None):
    """A stale/unreadable census is UNKNOWN, never zero orphaned duties."""
    now = time.time() if now is None else now
    try:
        report = _read(Path(root) / 'duties/report.json')
        if not report['complete'] or not 0 <= now - report['checked_at'] <= 900:
            raise ValueError('duty census stale or partial')
        count = sum(report['orphaned'][kind] for kind in KINDS)
        return f'Duties: {count} orphaned (fresh declared inventory)'
    except (OSError, ValueError, KeyError, TypeError):
        return 'Duties: UNKNOWN (census missing, stale or partial)'


def metrics(root, *, now=None):
    now = time.time() if now is None else now
    report = _read(Path(root) / 'duties/report.json')
    fresh = 0 <= now - report['checked_at'] <= 900
    ok = bool(report['complete'] and fresh)
    lines = [f'shantytown_duty_census_complete {int(ok)}',
             f'shantytown_duty_census_timestamp_seconds {report["checked_at"]}']
    if ok:
        for kind in KINDS:
            value = report['orphaned'][kind]
            if type(value) is not int or value < 0:
                raise ValueError('invalid duty count')
            lines.append(f'shantytown_orphaned_duties{{kind="{kind}"}} {value}')
    return '\n'.join(lines) + '\n'


def main():
    """Managed plan/check/apply and bounded read-only report, no shell hooks."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--plan-sha256')
    parser.add_argument('--expected-revision', type=int)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--metrics', action='store_true')
    args = parser.parse_args()
    if args.plan is None:
        if args.apply or args.expected_revision is not None or args.plan_sha256 is not None:
            parser.error('apply/revision requires a plan')
        print(metrics(args.root) if args.metrics else summary(args.root), end='\n')
        return
    if args.metrics or args.expected_revision is None:
        parser.error('plan requires its exact expected revision, not metrics')
    print(json.dumps(Duties(args.root).install(_read(args.plan, expected_sha256=args.plan_sha256),
        expected_revision=args.expected_revision, apply=args.apply), sort_keys=True))


if __name__ == '__main__':
    main()
