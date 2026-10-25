"""Private custody for text st put into a Codex composer.

This is not a second inbox. It records ownership before typing, so the existing
tend pass can recover a failed send without borrowing a human's draft.
# arming: library; send boundary and the existing scheduled tend pass.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

# A body is finished when it was submitted, its pointer was read, or a newer
# notice from the same owner replaced it. A superseded body is never resent.
TERMINAL = ('delivered', 'acknowledged', 'superseded')


class Custody:
    def __init__(self, root, pane, socket=None):
        self.root = Path(root) / 'delivery'
        self.pane, self.socket = pane, socket
        self.record = None

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink() or self.root.stat().st_uid != os.getuid():
            raise OSError('delivery custody directory is not owned locally')
        os.chmod(self.root, 0o700)
        key = hashlib.sha256(json.dumps([self.socket, self.pane]).encode()).hexdigest()
        fd = os.open(self.root / (key + '.lock'),
                     os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        self.lock = os.fdopen(fd, 'a')
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise OSError('another delivery owns this pane') from None
        return self

    def __exit__(self, *_):
        self.lock.close()

    def save(self, record):
        fd, name = tempfile.mkstemp(dir=self.root, prefix='.pending-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(record, stream)
            os.replace(name, self.root / (record['id'] + '.json'))
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def records(self):
        for path in sorted(self.root.glob('send-*.json')):
            if path.is_symlink():
                raise OSError('delivery custody record is a symlink')
            record = json.loads(path.read_text())
            if record['pane'] == self.pane and record['socket'] == self.socket:
                yield record

    def begin(self, text, session):
        # A retry retains the first timestamp and the same recovery episode.
        matches = [r for r in self.records() if r['text'] == text
                   and r['session'] == session
                   and r['state'] not in TERMINAL]
        if len(matches) > 1:
            raise OSError('ambiguous delivery custody')
        self.record = matches[0] if matches else dict(
            id='send-' + uuid.uuid4().hex, pane=self.pane, socket=self.socket,
            text=text, session=session, created=time.time(), state='prepared',
            recovery_attempted=False)
        self.record['state'] = 'prepared'
        self.save(self.record)

    def finish(self, state):
        if self.record is not None:
            self.record['state'] = state
            self.save(self.record)

    def failed(self, panes):
        if self.record is None:
            return
        from . import triage
        from .tmux import _codex_owned_input, _codex_queued
        record = self.record
        self.finish('unknown')
        screen = panes.capture(self.pane, attrs=True, timeout=2)
        if _codex_queued(screen, record['text']):
            self.finish('queued')
            return
        # Unknown session identity, busy state, multiline buffers and changed
        # text authorize no edits. Leave the body in custody and escalate.
        if (record['session'] is None or '\n' in record['text']
                or triage.mid_flight(screen)):
            return
        for key in ('C-e', 'C-u'):
            screen = panes.capture(self.pane, attrs=True, timeout=2)
            if (not _codex_owned_input(screen, record['text'])
                    or triage.mid_flight(screen)
                    or not panes._confirmed_codex(self.pane, panes.foreground(self.pane))
                    or panes.session_created(self.pane) != record['session']):
                return
            panes.control(self.pane, key)
        time.sleep(0.15)
        screen = panes.capture(self.pane, attrs=True, timeout=2)
        if triage.input_state(screen) in (triage.INPUT_EMPTY, triage.INPUT_PLACEHOLDER):
            self.finish('cleared')

    def clear_previous(self, panes, screen):
        """A later sender may unblock only an earlier owned, failed send.

        `queued` counts as failed once Codex has moved that exact body back into
        an idle composer (aegis-185l: a GOVERNOR HOLD notice sat there for 10h,
        and every later send was refused because only `unknown` was eligible).
        A superseded body is cleared but stays superseded, so it is never resent.
        """
        from .tmux import _codex_owned_input
        matches = [r for r in self.records()
                   if r['state'] in ('unknown', 'queued', 'superseded')
                   and r['session'] is not None
                   and r['session'] == panes.session_created(self.pane)
                   and _codex_owned_input(screen, r['text'])]
        if len(matches) != 1:
            return False
        self.record = matches[0]
        original = self.record['state']
        try:
            self.failed(panes)
            return self.record['state'] == 'cleared'
        finally:
            # failed() persists `unknown` before it captures the pane. On every
            # path, a raised capture included, a superseded body stays terminal:
            # an `unknown` one would be resubmitted by the next tend pass.
            if original == 'superseded':
                self.finish('superseded')
            self.record = None


def supersede(root, is_stale, *, keep):
    """Mark every unfinished body `is_stale` accepts, except `keep`, superseded.

    For notices that describe state rather than carry mail (quiet-time hold and
    lift): once the state moves on, the old text is wrong, so it must neither be
    resent nor get a pointer. Typed text is left alone here; the next send to an
    idle composer clears it through clear_previous. A pane whose custody lock is
    busy is skipped and retried on the next transition. Returns the record ids.
    """
    directory = Path(root) / 'delivery'
    if not directory.is_dir():
        return []
    panes = set()
    for path in directory.glob('send-*.json'):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if record.get('state') not in TERMINAL and is_stale(record.get('text', '')):
            panes.add((record['pane'], record['socket']))
    done = []
    for pane, socket in sorted(panes, key=lambda key: (key[0], str(key[1]))):
        try:
            with Custody(root, pane, socket) as custody:
                for record in custody.records():
                    if (record['state'] not in TERMINAL and record['text'] != keep
                            and is_stale(record['text'])):
                        record['state'] = 'superseded'
                        custody.save(record)
                        done.append(record['id'])
        except OSError:
            continue
    return done


STALL_SECONDS = 300
# aegis-185l. The backlog watch below re-arms only on an EMPTY backlog, which a
# busy agent never reaches, so it fired once on 10-20 and then stayed silent
# while panes were stranded for 3h and 10h. These two conditions are episodic
# on their own evidence, whatever the backlog holds.
STRANDED_SECONDS = 900
FAILED_SENDS = 5


def supervise(root, reg, card, panes, box, screen, *, now=None, deadline=None):
    """One bounded existing-tend observation; no agent is woken to poll mail."""
    from . import triage
    from .events import FilesEvents
    from .tier import route_stop, deployment_catalog
    from .tmux import _codex_owned_input
    now = time.time() if now is None else now
    try:
        messages = box.unread(card.name)
        readable = True
    except Exception:
        # A failed inbox read must not disable the independent local alert.
        # The empty working list below is NOT an empty-inbox observation.
        messages, readable = [], False
    socket = getattr(panes, 'socket', None)
    pending = []
    with Custody(root, card.pane, socket) as custody:
        observed = list(custody.records())
        for record in observed:
            if record['state'] in TERMINAL:
                continue
            marker = '[st delivery ' + record['id'] + ']'
            matches = [m for m in messages
                       if m.body == record['text'] or marker in m.body]
            if len(matches) > 1:
                record['pointer_state'] = 'ambiguous'
                custody.save(record)
                pending.append(record)
                continue
            if len(matches) == 1:
                record['pointer'] = matches[0].id
                record['receipt_marker'] = (marker if marker in matches[0].body
                                            else record['text'].rsplit(' ', 1)[0])
                record['pointer_state'] = 'recorded'
                custody.save(record)
            elif (readable and record.get('pointer_state') == 'recorded'
                  and not matches):
                # Disappearance from unread is not acknowledgement: the row
                # may have been deleted. Use the existing optional receipt
                # reader, including read rows, and verify the exact ID.
                reader = getattr(box, 'find_delivery', None)
                try:
                    receipt = reader(card.name, record['receipt_marker']) if reader else None
                except Exception:
                    receipt = None
                    readable = False
                if receipt and receipt.id == record['pointer'] and receipt.read:
                    record['state'] = 'acknowledged'
                    custody.save(record)
                    continue
            elif readable and not record.get('pointer_state'):
                # Persist intent before calling the board: a timeout may follow
                # a committed write. Never create another pointer blindly.
                record['pointer_state'] = 'attempting'
                custody.save(record)
                item = box.deliver(card.name, marker + ' Notice was not confirmed '
                                   'submitted. Retained body: delivery/' + record['id'] +
                                   '.json under this deployment root. Inspect with '
                                   '`st agent input ' + card.name + ' --show`.', frm='st tend')
                record['pointer'] = item.id
                record['receipt_marker'] = marker
                record['pointer_state'] = 'recorded'
                custody.save(record)
            pending.append(record)

    # ONE recovery attempt per retained body; never type into a queued, busy,
    # foreign, reused-session or unreadable composer. Release the custody lock
    # before using send(), which acquires the same lock itself.
    for record in pending:
        if deadline is not None and time.monotonic() >= deadline:
            break
        if (not readable or record.get('pointer_state') != 'recorded'
                or record.get('recovery_attempted') or record['session'] is None
                or panes.session_created(card.pane) != record['session']
                or triage.mid_flight(screen)):
            continue
        owned = _codex_owned_input(screen, record['text'])
        empty = triage.input_state(screen) in (triage.INPUT_EMPTY, triage.INPUT_PLACEHOLDER)
        if not owned and not (record['state'] == 'cleared' and empty):
            continue
        with Custody(root, card.pane, socket) as custody:
            record['recovery_attempted'] = True
            custody.save(record)
        try:
            if owned:
                panes.submit_owned(card.pane, record['text'], deadline=deadline)
            else:
                panes.send(card.pane, record['text'])
        except Exception:
            # Preserve uncertainty and the pointer. A later pass escalates, not
            # another automated resend. No exception text/body enters the alert.
            with Custody(root, card.pane, socket) as custody:
                custody.record = next(r for r in custody.records() if r['id'] == record['id'])
                custody.failed(panes)
        else:
            with Custody(root, card.pane, socket) as custody:
                record['state'] = 'delivered'
                custody.save(record)
            if record.get('pointer'):
                box.mark_read(card.name, ids=[record['pointer']])
            pending.remove(record)
        break

    if reg is not None:
        _stranded_watch(root, reg, card, panes, socket, screen, observed, now)

    # Age means observed unresolved, not an invented creation timestamp for a
    # legacy inbox row. A continuous backlog retains its first observation even
    # when another message arrives. Only an empty backlog rearms the episode.
    with Custody(root, card.pane, socket) as custody:
        name = 'watch-' + hashlib.sha256(card.name.encode()).hexdigest()
        path = custody.root / (name + '.json')
        if path.is_symlink():
            raise OSError('delivery observation is a symlink')
        if readable and not pending and not messages:
            path.unlink(missing_ok=True)
            return
        first = min([now] + [r['created'] for r in pending])
        watch = json.loads(path.read_text()) if path.exists() else dict(id=name, since=first)
        custody.save(watch)
        if watch.get('alerted') or now - watch['since'] < STALL_SECONDS or reg is None:
            return
        catalog = deployment_catalog(root)
        recipient = route_stop(reg, card.name, catalog=catalog).to
        state = triage.input_state(screen)
        busy = triage.mid_flight(screen)
        detail = (f'{card.name}: undelivered inbox/custody observed for at least '
                  f'{int(now - watch["since"])}s; box={state}; '
                  f'busy={busy}; retained={len(pending)}; '
                  f'unread={len(messages) if readable else "UNKNOWN"}. '
                  f'Inspect `st agent input {card.name} --show` and `st inbox {card.name}`. '
                  'No foreign draft was cleared; queued input is not delivery.')
        FilesEvents(Path(root) / 'events').persist(
            recipient, card.name, 'delivery-stalled', False, detail=detail,
            key=f'delivery-stalled:{card.name}:{watch["since"]}')
        watch['alerted'] = True
        custody.save(watch)
    # One incident wake on the normal coordinator path, not a poll that wakes
    # the stalled agent to check its mail. A queued/failed wake retains the
    # durable event and never burns another send on the next tend pass.
    try:
        from .notify import wake_recipient
        wake_recipient(reg, panes, card.name, detail, catalog=catalog)
    except Exception:
        pass


def _stranded_watch(root, reg, card, panes, socket, screen, records, now):
    """Page the lead when st's own text is stuck in an idle composer for 15 min,
    or FAILED_SENDS consecutive sends to the pane were never delivered.

    Each condition is its own episode. The composer episode re-arms when the
    composer stops holding that body; the send episode re-arms after a delivery.
    No body text enters the alert, and nothing here types into the pane.
    """
    from . import triage
    from .events import FilesEvents
    from .tier import route_stop, deployment_catalog
    from .tmux import _codex_owned_input
    records = sorted(records, key=lambda r: r['created'])
    owned = None
    if not triage.mid_flight(screen):
        owned = next((r for r in records if r['state'] not in ('delivered', 'acknowledged')
                      and _codex_owned_input(screen, r['text'])), None)
    last_ok = max((i for i, r in enumerate(records)
                   if r['state'] in ('delivered', 'acknowledged')), default=-1)
    failing = [r for r in records[last_ok + 1:]
               if r['state'] not in ('delivered', 'acknowledged')]
    with Custody(root, card.pane, socket) as custody:
        name = 'strand-' + hashlib.sha256(card.name.encode()).hexdigest()
        path = custody.root / (name + '.json')
        if path.is_symlink():
            raise OSError('delivery observation is a symlink')
        watch = json.loads(path.read_text()) if path.exists() else dict(id=name)
        alerts = []
        body = owned and hashlib.sha256(owned['text'].encode()).hexdigest()
        composer = watch.get('composer') or {}
        if body is None:
            watch.pop('composer', None)
        else:
            if composer.get('body') != body:
                composer = dict(body=body, since=now, alerted=False)
            watch['composer'] = composer
            if not composer['alerted'] and now - composer['since'] >= STRANDED_SECONDS:
                alerts.append((f'composer-stranded:{card.name}:{composer["since"]}',
                               f'{card.name}: st-typed notice unsubmitted in an idle composer '
                               f'for {int(now - composer["since"])}s; every later send is '
                               'refused until it clears'))
                composer['alerted'] = True
        episode = failing[0]['id'] if len(failing) >= FAILED_SENDS else None
        sends = watch.get('sends') or {}
        if episode is None:
            watch.pop('sends', None)
        else:
            if sends.get('first') != episode:
                sends = dict(first=episode, alerted=False)
            watch['sends'] = sends
            if (not sends['alerted']
                    and now - failing[0]['created'] >= STRANDED_SECONDS):
                alerts.append((f'delivery-failing:{card.name}:{episode}',
                               f'{card.name}: {len(failing)} consecutive sends not delivered '
                               f'over {int(now - failing[0]["created"])}s (queued, unknown or '
                               'superseded)'))
                sends['alerted'] = True
        if watch.keys() == {'id'}:
            path.unlink(missing_ok=True)
        else:
            custody.save(watch)
    if not alerts:
        return
    catalog = deployment_catalog(root)
    recipient = route_stop(reg, card.name, catalog=catalog).to
    for key, summary in alerts:
        detail = (summary + f'; box={triage.input_state(screen)}. Inspect '
                  f'`st agent input {card.name} --show`. No foreign draft was cleared.')
        FilesEvents(Path(root) / 'events').persist(
            recipient, card.name, 'delivery-stalled', False, detail=detail, key=key)
        try:
            from .notify import wake_recipient
            wake_recipient(reg, panes, card.name, detail, catalog=catalog)
        except Exception:
            pass
