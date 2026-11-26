"""Plan-share USD per item from measured account-window utilization (aegis-59jx).

Flat plans have no per-token bill, so Camayoc's projection leaves
`plan_share_usd` null: it refuses to invent an allocation denominator from
transcript token counts, because the supplied sources are not a census of the
account. This module uses a different denominator that needs no census: the
account's own utilization reading. If an item's focus interval is the ONLY bound
focus on its account, the window points the account burned across that interval
are that item's, and the plan's price for the window converts points to dollars.

Every other case is UNKNOWN with a reason, never a guess:
- another focus on the same account overlaps the measured interval (the
  points cannot be split without the census Camayoc already refused to assume);
- the focus is still open, or no reading brackets it closely enough;
- the window reset between the two readings, or the reading went backwards;
- the agent's recorded launch postdates the focus start, so which account it
  used at the time is not known (launch stamps are overwritten per launch);
- no plan price is declared for the account.

The readings are bracketing samples, so the measured interval is slightly wider
than the focus. Exclusivity is checked against that wider interval, not the
focus itself, so a neighbour inside the gap cannot leak its burn into this item.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

MAX_GAP = 900
"""Seconds a bracketing reading may sit outside the focus interval.

Minute-scheduled scrapes leave ample slack; a wider gap would attribute burn
from well outside the focus to it.
"""


def _readings(path):
    rows = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            rows.append({'account': str(row['account']), 'window': str(row['window']),
                         'ts': float(row['ts']), 'pct': float(row['pct']),
                         'resets_at': row.get('resets_at')})
    return sorted(rows, key=lambda r: r['ts'])


def launch_accounts(root):
    """Agent -> (account, born) from the governor's launch stamps."""
    result = {}
    for path in (Path(root) / 'governor' / 'account-launches').glob('*.json'):
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if value.get('account'):
            result[path.stem] = (value['account'], value.get('born'))
    return result


def _bracket(readings, account, window, start, end):
    rows = [r for r in readings if r['account'] == account and r['window'] == window]
    before = [r for r in rows if r['ts'] <= start]
    after = [r for r in rows if r['ts'] >= end]
    if not before or not after:
        return None, 'no reading brackets the focus'
    first, last = before[-1], after[0]
    if start - first['ts'] > MAX_GAP or last['ts'] - end > MAX_GAP:
        return None, f'nearest readings exceed {MAX_GAP}s from the focus'
    if first['resets_at'] is None or first['resets_at'] != last['resets_at']:
        return None, 'window reset (or unknown reset) between readings'
    if last['pct'] < first['pct']:
        return None, 'utilization decreased between readings'
    return (first, last), None


def _same(a, b):
    return all(a.get(k) == b.get(k) for k in ('agent', 'session', 'bead', 'start'))


def allocate(bindings, readings, plans, accounts, everyone=None):
    """One row per binding: measured plan-share USD, or None with a reason.

    `everyone` is every declared focus fleet-wide, not just the sampled
    sources: a concurrent focus filtered out of the sample still shares the
    account, and checking only the sample would call that interval exclusive.
    """
    everyone = bindings if everyone is None else everyone
    rows = []
    for binding in bindings:
        row = {k: binding.get(k) for k in ('rig', 'bead', 'agent', 'session', 'start', 'end')}
        row.update(account=None, window=None, points=None, usd=None, reason=None)
        rows.append(row)
        account, born = accounts.get(binding['agent'], (None, None))
        if binding.get('end') is None:
            row['reason'] = 'focus still open'
            continue
        if account is None:
            row['reason'] = 'no recorded launch account for agent'
            continue
        if born is None or float(born) > binding['start']:
            row['reason'] = 'account at focus start unknown (launch postdates it or unstamped)'
            continue
        row['account'] = account
        plan = plans.get(account)
        if not plan:
            row['reason'] = 'no plan price declared for account'
            continue
        row['window'] = plan['window']
        pair, why = _bracket(readings, account, plan['window'], binding['start'], binding['end'])
        if pair is None:
            row['reason'] = why
            continue
        lo, hi = pair[0]['ts'], pair[1]['ts']
        # Includes this agent's own next focus: inside the reading gap its burn
        # is indistinguishable from this one's.
        shared = [b for b in everyone if not _same(b, binding)
                  and accounts.get(b['agent'], (None,))[0] == account
                  and b['start'] < hi and (b.get('end') is None or b['end'] > lo)]
        if shared:
            row['reason'] = f'account shared with {len(shared)} other focus(es) in the measured interval'
            continue
        # A live agent with no declared focus still burns the account's window,
        # and a focus list cannot see it. Occupancy comes from launch stamps: any
        # other agent on this account by then shares it, and any agent launched
        # after the interval began was on an account we cannot name.
        occupied = sorted(a for a, (acct, launched) in accounts.items() if a != binding['agent']
                          and (launched is None or float(launched) > lo
                               or (acct == account and float(launched) <= hi)))
        if occupied:
            row['reason'] = 'account occupancy not exclusive or unknown: ' + ', '.join(occupied)
            continue
        try:
            window_usd = (Decimal(str(plan['usd'])) * Decimal(str(plan['window_days']))
                          / Decimal(str(plan['period_days'])))
        except (KeyError, InvalidOperation, ZeroDivisionError):
            row['reason'] = 'malformed plan price'
            continue
        points = Decimal(str(pair[1]['pct'])) - Decimal(str(pair[0]['pct']))
        row['points'] = str(points)
        row['usd'] = str(window_usd * points / Decimal(100))
    return rows


def project(root, config, bindings, everyone):
    """Read the configured inputs; None when plan share is not enabled."""
    settings = config.get('plan_share')
    if not settings:
        return None
    return allocate(bindings, _readings(settings['readings_file']), settings['plans'],
                    launch_accounts(root), everyone)


def describe(rows, bead):
    mine = [r for r in (rows or []) if r['bead'] == bead]
    if rows is None:
        return None
    if not mine:
        return 'Plan share USD: UNKNOWN (no focus interval for this item)'
    known = [Decimal(r['usd']) for r in mine if r['usd'] is not None]
    unknown = len(mine) - len(known)
    head = (f'Plan share USD (measured window points x plan price): {sum(known, Decimal(0))}'
            if not unknown else
            f'Plan share USD: UNKNOWN (known subtotal {sum(known, Decimal(0))} over '
            f'{len(known)}/{len(mine)} focus interval(s))')
    lines = [head]
    for r in mine:
        value = r['usd'] if r['usd'] is not None else 'UNKNOWN (' + r['reason'] + ')'
        lines.append(f"  {r['agent']} / {r['account'] or 'UNKNOWN'} / {r['window'] or 'UNKNOWN'}: {value}"
                     + (f"; {r['points']} points" if r['points'] is not None else ''))
    return '\n'.join(lines)


def metrics(rows):
    lines = ['# TYPE st_bead_plan_share_usd gauge']
    for r in rows or []:
        if r['usd'] is None:
            continue
        labels = {k: r[k] or 'UNKNOWN' for k in ('rig', 'bead', 'agent', 'account', 'window')}
        labels['interval_start'] = str(int(r['start']))
        label = ','.join(f'{k}={json.dumps(str(v))}' for k, v in labels.items())
        lines.append(f"st_bead_plan_share_usd{{{label}}} {r['usd']}")
    return '\n'.join(lines) + '\n'
