"""Explicit queue admission; missing metadata never becomes a passing plate.

Activation is a deployment choice: old unlaned boards need migration before
enforcement. This module never moves an existing item to manufacture admission.
"""
from decimal import Decimal
import json
import math
from pathlib import Path

from .protocols import plate_key, rank_order
from .priority_advisory import workable
from .inbox import drop_parked


def enabled(value):
    if value in (None, '', 'off'):
        return False
    if value == 'enforce':
        return True
    raise ValueError('queue policy UNKNOWN; choose off or enforce')


def validate(rows):
    if not isinstance(rows, list) or len(rows) > 45:
        raise ValueError('queue coverage UNKNOWN or capped')
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or not row['id'] or row['id'] in seen
                or row.get('lane') not in ('now', 'next')
                or row.get('status') not in ('open', 'in_progress', 'hooked', 'blocked', 'deferred')):
            raise ValueError('queue identity, lane or lifecycle UNKNOWN')
        rank_order(row.get('rank'), row.get('due_at'), row.get('created_at'))
        seen.add(row['id'])
    if sum(r['lane'] == 'now' for r in rows) > 5 or sum(r['lane'] == 'next' for r in rows) > 40:
        raise ValueError('queue cap exceeded; no inferred displacement')
    return rows


def key(row):
    return (*rank_order(row.get('rank'), row.get('due_at'), row.get('created_at')), row['id'])


def intake(rows):
    rows = validate(rows)
    pending = [r for r in rows if r['lane'] == 'next']
    if len(pending) >= 40:
        raise ValueError('Next is full (40); choose and record a displacement first')
    ranks = [Decimal(r['rank']) for r in pending if r.get('rank') is not None]
    # An unranked predecessor would sort after every ranked new request. Do not
    # quietly jump it by assigning a plausible-looking new decimal.
    if len(ranks) != len(pending):
        raise ValueError('Next contains unranked work; append position UNKNOWN')
    rank = format(max(ranks, default=Decimal(0)) + 1, 'f')
    rank_order(rank)
    active = sorted((r for r in rows if r['lane'] == 'now'), key=key)
    return {'lane': 'next', 'rank': rank, 'position': len(pending) + 1,
            'likely_start': 'UNKNOWN (no duration/availability evidence)',
            'would_pause': [r['id'] for r in active]}


def reply(ident, plan):
    pauses = ', '.join(plan['would_pause']) or 'none currently in Now'
    return (f"{ident}: Next position {plan['position']}, rank {plan['rank']}; "
            f"likely start: {plan['likely_start']}; requesting now would require "
            f"an explicit disposition of: {pauses}.")


def refusal(item, owner, rows):
    if item.lane is None:
        return f'{item.id} lane UNKNOWN; no dispatch'
    if item.lane != 'now':
        return f'{item.id} is not in Now; quoted promotion is required before dispatch'
    if item.rank is None:
        return f'{item.id} rank UNKNOWN; dispatch refused'
    # rows are the complete target-owner projection, not the global backlog.
    candidates = [r for r in drop_parked(rows) if workable(r)
                  and (r.get('assignee') or '').split('/')[-1] == owner.split('/')[-1]
                  and r.get('status') != 'closed']
    candidate = dict(vars(item))
    candidates = [r for r in candidates if r.get('id') != item.id] + [candidate]
    for row in candidates:
        if row.get('lane') not in ('now', 'next', 'later') or row.get('rank') is None:
            return f"plate ordering UNKNOWN at {row.get('id', '?')}; no dispatch"
        rank_order(row['rank'], row.get('due_at'), row.get('created_at'))
    top = min(candidates, key=lambda r: plate_key(r.get('status'), r.get('priority'),
        r['id'], rank=r.get('rank'), due_at=r.get('due_at'),
        created_at=r.get('created_at'), lane=r.get('lane')))
    if top['id'] != item.id:
        return f"{item.id} is out of order; {top['id']} heads {owner}'s ranked plate"
    return ''


def promotion(quote, requester, urgent, *, displaced=()):
    if (not isinstance(quote, str) or not quote.strip()
            or not isinstance(requester, str) or not requester.strip() or urgent is not True):
        raise ValueError('Now promotion requires --quote, --requester and --urgent')
    return json.dumps({'schema': 'queue-promotion/v1', 'quote': quote,
        'requester': requester, 'urgent': True, 'displaced': list(displaced)}, sort_keys=True)


def stage(tracker, item, plan):
    """A created ID survives a failed lane CAS; callers print it, never retry."""
    before = tracker.get(item.id)
    if type(before.revision) is not int or before.revision < 1:
        raise ValueError('created item revision UNKNOWN; retain ID, no intake retry')
    tracker.update(item.id, lane='next', rank=plan['rank'], if_revision=before.revision,
        transition_comment=json.dumps({'schema': 'queue-intake/v1', 'lane': 'next',
            'rank': plan['rank']}, sort_keys=True))
    after = tracker.get(item.id)
    if after.lane != 'next' or after.rank != plan['rank']:
        raise RuntimeError('queue intake readback UNKNOWN; retain ID, no retry')
    rows = validate(tracker.queue_rows())
    pending = sorted((r for r in rows if r['lane'] == 'next'), key=key)
    matches = [i for i, row in enumerate(pending) if row['id'] == item.id]
    if len(matches) != 1:
        raise RuntimeError('intake position coverage UNKNOWN; retain ID, no retry')
    return plan | {'position': matches[0] + 1,
                   'would_pause': [r['id'] for r in sorted(rows, key=key) if r['lane'] == 'now']}


def gate(tracker, previous=None, *, audit=None, dry_run=False):
    def check(item, owner):
        if previous is not None:
            reason = previous(item, owner)
            if reason:
                return reason
        try:
            rows = (tracker.queue_owner_rows(owner)
                    if item.lane == 'now' and item.rank is not None else [])
            reason = refusal(item, owner, rows)
        except Exception as error:
            reason = f'queue admission UNKNOWN ({type(error).__name__}: {error}); no dispatch'
        if reason and audit is not None and not dry_run:
            try:
                audit.record(audit.begin(), leg='queue', worker=owner, item=item.id,
                    refused=True, reason=reason,
                    state='queue_order_unknown' if 'UNKNOWN' in reason else 'queue_order_refused')
            except Exception as error:
                return f'queue audit UNKNOWN ({type(error).__name__}); no dispatch'
        return reason
    return check


def observations(root, *, since=0, owner=None):
    """A retained audit is not an all-history total or proof of activation."""
    unknown = {'status': 'UNKNOWN', 'out_of_order_attempts': None,
               'scope': 'retained local feed audit; not historical fleet total',
               'since_epoch': since, 'owner': owner}
    path = Path(root) / 'logs/feed-audit.jsonl'
    try:
        with path.open('rb') as handle:
            raw = handle.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            return unknown | {'reason': 'audit byte budget reached'}
        rows = [json.loads(line) for line in raw.splitlines()]
        if not rows or any(not isinstance(row, dict) for row in rows):
            return unknown | {'reason': 'audit empty or malformed'}
        selected = [row for row in rows if row.get('state') in (
            'queue_order_refused', 'queue_order_unknown')]
        if not selected:
            return unknown | {'reason': 'no queue admission observation retained'}
        if any(row.get('leg') != 'queue' or row.get('refused') is not True
               or not row.get('item') or not row.get('worker')
               or type(row.get('at')) not in (int, float)
               or not math.isfinite(row['at']) for row in selected):
            return unknown | {'reason': 'queue audit malformed'}
        selected = [row for row in selected if row['at'] >= since
                    and (owner is None or row['worker'] == owner)]
        count = sum(row['state'] == 'queue_order_refused' for row in selected)
        return unknown | {'status': 'PARTIAL' if count != len(selected) else 'OBSERVED',
                          'out_of_order_attempts': count,
                          'unknown_attempts': len(selected) - count,
                          'observations': selected}
    except (OSError, ValueError, UnicodeError):
        return unknown | {'reason': 'audit missing or unreadable'}
