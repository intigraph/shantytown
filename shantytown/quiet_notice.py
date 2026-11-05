"""Operational quiet-time transitions, separate from routine budget advice.

No detector, hold, quota or lifecycle mutation. Delivery failures remain pending.
"""
from __future__ import annotations

import fcntl
import json
import time
from pathlib import Path

from .files import write_json_atomic

LONG_HOLD_SECONDS = 1800
# Every hold/lift notice carries this, so its custody can be told apart from mail.
NOTICE_MARK = ' Re-check st fleet hold all --status before honouring hold notes;'


# How each quiet-time render begins (quiet_time.Status.render, gaming render).
_NOTICE_STARTS = ('GOVERNOR HOLD', 'QUIET-TIME HOLD LIFTED',
                  'quiet-time observation UNKNOWN', 'quiet-time detection off')


def is_notice(text):
    """A hold/lift notice tend itself typed: its own attribution, a quiet-time
    render, and the marker. Mail that merely quotes the marker is still mail."""
    from .attribution import ST_TEND, attribute
    prefix = attribute('', ST_TEND)
    if not text.startswith(prefix):
        return False
    body = text[len(prefix):]
    return body.startswith(_NOTICE_STARTS) and NOTICE_MARK in body


def metrics(root):
    """Pending operational delivery is visible to the normal alerting tier."""
    try:
        data = json.loads((Path(root)/'notify/quiet_time_delivery.json').read_text())
        pending = len(data.get('pending', [])) + int(bool(data.get('page_pending')))
    except FileNotFoundError:
        pending = 0
    except (OSError, ValueError, TypeError, AttributeError):
        pending = 1  # unreadable is not successful delivery
    return ('# TYPE aegis_quiet_time_notice_pending gauge\n'
            f'aegis_quiet_time_notice_pending {pending}\n')


def sweep(root, status, reg, panes, *, slowdown_unknown=False, now=None,
          push=None, page=None):
    from .notify import push_to_admin, push_to_own_pane
    push = push or push_to_own_pane
    page = page or push_to_admin
    now = time.time() if now is None else now
    path = Path(root) / 'notify' / 'quiet_time_delivery.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            data = {}
            # Upgrade during a hold must still announce its first observed lift.
            legacy = path.with_name('gaming_hold.json')
            if legacy.exists():
                record = json.loads(legacy.read_text()).get('local', {})
                old_key = record.get('key') if isinstance(record, dict) else record
                if isinstance(old_key, str) and old_key.startswith('held:'):
                    data['legacy_held'] = old_key
        # A corrupt ledger must not silently erase undelivered recipients.
        if not isinstance(data, dict):
            raise ValueError('invalid quiet-time delivery ledger')
        reasons = tuple(getattr(status, 'reasons', ('gaming',) if status.held else ()))
        entries = getattr(status, 'entries', (('gaming', status),))
        unknown = any(value.state == 'unknown' for _, value in entries)
        key = ('held:' + ','.join(reasons) if status.held else
               'unknown' if status.state == 'unknown' else 'clear')
        old = data.get('key', data.get('legacy_held'))
        if key != old or 'key' not in data:
            data['held_since'] = (data.get('held_since', now)
                                  if status.held and str(old).startswith('held:') else now)
            data['key'] = key
            data['since'] = now
            data['warned'] = False
            # Initial clear is no event. A real lift reaches every live pane,
            # including workers who only saw another worker's hold notes.
            if old is not None or status.held or key == 'unknown':
                cards = reg.all().exact()
                data['pending'] = sorted(c.name for c in cards
                                         if c.pane and panes.exists(c.pane))
                data['message'] = (status.render() + NOTICE_MARK +
                    ' an elapsed note is not current authority.')
                # A hold or lift notice describes state. Once the state moves
                # on, an earlier one still in a composer is wrong and blocks
                # every later send (aegis-185l: 3h and 10h). Supersede it, so it
                # is never resent; the next send clears it from an idle composer.
                from .attribution import ST_TEND, attribute
                from .delivery import supersede
                try:
                    supersede(getattr(panes, 'delivery_root', None) or root, is_notice,
                              keep=attribute(data['message'], ST_TEND))
                except OSError:
                    pass  # custody unreadable: the notice itself still goes out
            else:
                data['pending'] = []
            data['page_pending'] = unknown
            data['page_kind'] = 'unknown'
            data['page_message'] = 'quiet-time observation UNKNOWN; inspect scheduled probe and current hold status.'
        if unknown and not data.get('unknown'):
            data['page_pending'] = True
            data['page_kind'] = 'unknown'
            data['page_message'] = 'quiet-time observation UNKNOWN; inspect scheduled probe and current hold status.'
        data['unknown'] = unknown
        if (status.held and now - data.get('held_since', now) >= LONG_HOLD_SECONDS
                and not data.get('warned')):
            data['page_pending'] = True
            data['page_kind'] = 'long'
            data['page_message'] = ('quiet-time hold has lasted at least 30 minutes;'
                                    ' verify the detector with the operator. Do not clear it automatically.')
        if slowdown_unknown and not data.get('slowdown_unknown'):
            data['page_pending'] = True
            data['page_kind'] = 'slowdown'
            data['page_message'] = ('quiet-time slowdown verification UNKNOWN;'
                                    ' detector state and scope provenance are separate. Inspect the probe journal.')
        data['slowdown_unknown'] = slowdown_unknown
        # Journal the pending event before any delivery; a crash cannot mark an
        # unsent event delivered. Pane arrival remains the caller's acceptance.
        write_json_atomic(path, data)
        sent = []
        if data.get('page_pending') and page(reg, panes, data['page_message']):
            data['page_pending'] = False
            if data.get('page_kind') == 'long':
                data['warned'] = True
            write_json_atomic(path, data)
        for name in list(data.get('pending', [])):
            if push(reg, panes, name, data['message']):
                data['pending'].remove(name)
                write_json_atomic(path, data)
                sent.append(name)
        return sent
