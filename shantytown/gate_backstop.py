"""Ordering is not a dependency (aegis-r09); observe in the existing tend pass."""
from __future__ import annotations
import hashlib
import re
from datetime import timedelta
from pathlib import Path
from .deferrals import parse_conditions, parse_stamp
from .files import write_json_atomic
import json


def field(text, name):
    values = re.findall(r'^' + re.escape(name) + r':[ \t]*(.+)$', text or '', re.M)
    return values[0].strip() if len(values) == 1 else None


def steve_ask(notes):
    """Original quote/time/source, never dateModified masquerading as ask time."""
    quote, source, raw = (field(notes, k) for k in
                          ('steve_quote', 'steve_source', 'steve_ask_at'))
    stamp = parse_stamp(raw)
    if (not quote or not source or not raw or not re.fullmatch(
            r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z', raw)):
        return None
    return stamp


def closed_gate(notes):
    conditions = parse_conditions(notes or '')
    return conditions[0].arg if len(conditions) == 1 and conditions[0].kind == 'closed' else None


def scope(notes):
    return tuple(field(notes, k) for k in ('repo', 'epic'))


def validate_gate(item, target, reason, sattler_reason='', authority=''):
    if not reason.strip() or '\n' in reason.strip() or '\r' in reason.strip():
        raise ValueError('closed gate requires --dependency-reason: one-line technical dependency; queue order is not a gate')
    if item.id == target.id:
        raise ValueError('an item cannot gate on itself')
    if (type(item.priority) is not int or type(target.priority) is not int
            or not 0 <= item.priority <= 4 or not 0 <= target.priority <= 4):
        raise ValueError('gate priorities are UNKNOWN; set both before deferring')
    notes = item.notes or ''
    if (steve_ask(notes) or field(notes, 'steve_quote')) and target.priority > item.priority:
        if authority != 'sattler' or not sattler_reason.strip() or '\n' in sattler_reason.strip():
            raise ValueError('Steve ask behind lower priority requires Sattler --sattler-reason before inheritance')
    return min(item.priority, target.priority)


class Backstop:
    """Delivery-aware, bounded chain observation. No release or item writes."""
    def __init__(self, root, now, deliver, log=lambda text: None):
        self.path = Path(root) / 'notify' / 'gate-backstop.json'
        self.now, self.deliver, self.log = now, deliver, log
        try:
            self.state = json.loads(self.path.read_text())
            if not isinstance(self.state, dict):
                raise ValueError('invalid ledger')
        except FileNotFoundError:
            self.state = {}
        # Corrupt state must not turn into an empty dedup ledger and replay wakes.

    def run(self, rows, lookup, lookup_many=None):
        cache = {r['id']: r for r in rows if isinstance(r, dict) and r.get('id')}
        reads = 0
        offset = self.state.get('_cursor', {}).get('offset', 0)
        offset = offset % len(rows) if rows and type(offset) is int else 0
        ordered = rows[offset:] + rows[:offset]
        if lookup_many is not None:
            targets = list(dict.fromkeys(closed_gate(row.get('notes') or '')
                           for row in ordered if isinstance(row, dict)))
            targets = [target for target in targets if target and target not in cache][:16]
            if targets:
                reads += len(targets)
                try:
                    projected = lookup_many(targets)
                    if not isinstance(projected, dict) or any(key not in targets for key in projected):
                        raise ValueError('invalid gate metadata batch')
                    cache.update({target:projected.get(target) for target in targets})
                except Exception as exc:
                    self.log(f'gate-backstop metadata batch UNKNOWN ({exc}); no serial fallback')
                    cache.update(dict.fromkeys(targets))
        def get(identifier):
            nonlocal reads
            if identifier not in cache:
                if reads >= 25:
                    raise ValueError('chain lookup budget reached')
                reads += 1
                cache[identifier] = lookup(identifier)
            row = cache[identifier]
            if not isinstance(row, dict) or row.get('id') != identifier or not row.get('status'):
                raise ValueError('chain target UNKNOWN')
            return row
        incoming = {}
        for candidate in rows:
            if not isinstance(candidate, dict) or not candidate.get('id'):
                continue
            if (candidate.get('status') in ('deferred', 'blocked') or candidate.get('defer_until')
                    or any(str(x).startswith('blocked:') for x in candidate.get('labels', []))):
                target = closed_gate(candidate.get('notes') or '')
                if target:
                    incoming.setdefault(target, []).append(candidate['id'])
        def chain_root(identifier):
            visited, pending = set(), [identifier]
            while pending and len(visited) <= 25:
                current = pending.pop()
                if current in visited:
                    continue
                visited.add(current)
                parents = incoming.get(current, [])
                if not parents:
                    return current == identifier
                pending.extend(parents)
            # A cycle has no parentless root: choose one stable representative.
            return bool(visited) and identifier == min(visited) and len(visited) <= 25
        active, delivered = {}, []
        delivered_count = 0
        def send(recipient, message):
            nonlocal delivered_count
            if delivered_count >= 12:
                self.log("gate-backstop delivery budget reached; remaining events pending")
                return False
            outcome = self.deliver(recipient, message)
            if outcome:
                delivered_count += 1
            return outcome
        for row in ordered:
            if not isinstance(row, dict) or not row.get('id'):
                continue
            notes = row.get('notes') or ''
            gate = closed_gate(notes)
            blocked = row.get('status') == 'deferred' or bool(row.get('defer_until')) or any(
                str(x).startswith('blocked:') for x in row.get('labels', []))
            if gate and blocked and chain_root(row["id"]):
                chain, current, reasons = [row['id']], row, []
                try:
                    for _ in range(8):
                        target_id = closed_gate(current.get('notes') or '')
                        if not target_id:
                            break
                        if target_id in chain:
                            chain.append(target_id)
                            reasons.append('dependency cycle')
                            break
                        target = get(target_id)
                        chain.append(target_id)
                        if target['status'] in ('closed', 'tombstone'):
                            break
                        target_scope = scope(target.get('notes') or '')
                        own_scope = scope(current.get('notes') or '')
                        if any(a and b and a != b for a,b in zip(own_scope,target_scope)):
                            reasons.append('cross-repo/epic gate requires Sattler ruling')
                        elif not any(a and b for a,b in zip(own_scope,target_scope)):
                            reasons.append('repo/epic scope UNKNOWN; Sattler must verify technical gate')
                        if target['status'] in ('deferred', 'blocked') or target.get('defer_until') or any(
                                str(x).startswith('blocked:') for x in target.get('labels', [])):
                            reasons.append('gate target is deferred/blocked')
                        observation_key = 'observed:' + target_id
                        signature = (target['status'], target.get('defer_until'),
                                     closed_gate(target.get('notes') or ''),
                                     sorted(str(x) for x in target.get('labels',[]) if str(x).startswith('blocked:')))
                        signature = json.dumps(signature)
                        old = self.state.get(observation_key, {})
                        since = parse_stamp(old.get('since')) if old.get('signature') == signature else None
                        since = since or self.now
                        active[observation_key] = {'root':row['id'], 'signature':signature,'since':since.isoformat()}
                        changed = parse_stamp(target.get('updated_at')) or since
                        if changed is not None and self.now - changed >= timedelta(hours=48):
                            reasons.append('gate target unchanged for at least 48h')
                        current = target
                    else:
                        raise ValueError('chain depth budget reached')
                except Exception as exc:
                    self.log(f"gate-backstop {row['id']}: UNKNOWN ({exc}); no release")
                    # Preserve delivery state across unreadable passes.
                    active.update({k:v for k,v in self.state.items() if v.get('root') == row['id']})
                    continue
                if reasons:
                    key = 'chain:' + hashlib.sha256('|'.join(chain).encode()).hexdigest()
                    previous = active.get(key, self.state.get(key, {}))
                    entry = {'root':row['id'], 'delivered':previous.get('delivered', False)}
                    if not entry['delivered'] and send('sattler', 'STALL ' + ' -> '.join(chain) + ': ' + '; '.join(dict.fromkeys(reasons))):
                        entry['delivered'] = True
                        delivered.append(row['id'])
                    active[key] = entry
            ask = steve_ask(notes)
            if ask is not None and ask > self.now:
                ask = None
            started_stamp = parse_stamp(field(notes, 'work_started_at'))
            started = row.get('status') in ('in_progress','closed','tombstone') or (
                started_stamp is not None and ask is not None and ask <= started_stamp <= self.now)
            if ask and not started and self.now - ask >= timedelta(hours=72):
                key = 'ask:' + row['id'] + ':' + ask.isoformat()
                previous = self.state.get(key, {})
                stage = previous.get('stage', 0)
                message = f"STEVE ASK NOT STARTED {row['id']} since {ask.isoformat()}; source: {field(notes,'steve_source')}; quote: {field(notes,'steve_quote')}"
                if stage == 0 and send('sattler', message):
                    stage = 1
                    delivered.append(row['id'])
                elif stage == 1 and send('hammond', message + '; prior Sattler delivery verified'):
                    stage = 2
                    delivered.append(row['id'])
                active[key] = {'root':row['id'], 'stage':stage}
            elif field(notes,'steve_quote') and not ask:
                key = 'ask-unknown:' + row['id']
                entry = {'root':row['id'], 'delivered':self.state.get(key, {}).get('delivered',False)}
                if not entry['delivered'] and send('sattler', f"STEVE ASK PROVENANCE UNKNOWN {row['id']}: original quote/time/source required; age is UNKNOWN"):
                    entry['delivered'] = True
                    delivered.append(row['id'])
                active[key] = entry
        active['_cursor'] = {'offset':(offset + 25) % len(rows) if rows else 0}
        self.path.parent.mkdir(parents=True,exist_ok=True)
        write_json_atomic(self.path, active)
        return delivered
