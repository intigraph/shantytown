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
#
# aegis-u2s adds two END-OF-CUSTODY states, both decided on evidence, never on
# elapsed time. Measured 2026-11-02: 7,539 'queued' records, none visible on any
# screen, and 8,324 non-terminal records belonged to sessions that no longer
# exist. Nothing could ever act on them (every action needs a session match),
# yet they kept the backlog non-empty, so the backlog watch latched fleet-wide.
#   orphaned  the record's session is not the pane's current session: the body
#             cannot be in this composer. Its durable inbox pointer, if any,
#             still carries the message.
#   dequeued  a queued body that the pane, observed idle with an empty composer,
#             no longer shows in any queue preview. It was submitted or
#             discarded; st cannot tell which, and an unread pointer still
#             counts as backlog either way.
END_OF_CUSTODY = ('orphaned', 'dequeued')
TERMINAL = ('delivered', 'acknowledged', 'superseded') + END_OF_CUSTODY


def observed_submission(root, pane, socket, text, session, created, runtime):
    """Read-only explicit submission proof; transport terminal states do not count.

    This repairs the crash between the transport's existing custody commit and
    the dispatch ledger's observation. It never enters Custody or edits input.
    """
    from .protocols import SubmissionObserved
    folder = Path(root) / 'delivery'
    if not folder.exists():
        return None
    if folder.is_symlink() or folder.stat().st_uid != os.getuid():
        raise OSError('delivery custody ownership UNKNOWN')
    recent = []
    for path in folder.glob('send-*.json'):
        if path.is_symlink():
            raise OSError('delivery custody record is a symlink')
        info = path.stat()
        if info.st_mtime + 1 < created:
            continue
        if info.st_uid != os.getuid() or info.st_size > 262144:
            raise OSError('delivery custody record unproven')
        recent.append(path)
        if len(recent) > 4096:
            raise OSError('recent delivery custody coverage bound exceeded')
    matches = []
    for path in recent:
        row = json.loads(path.read_text())
        if (row.get('pane') == pane and row.get('socket') == socket
                and row.get('text') == text and row.get('session') == session
                and row.get('state') == 'delivered'
                and row.get('submission') == dict(pane=pane,
                    body_sha256=hashlib.sha256(text.encode()).hexdigest(), runtime=runtime)
                and isinstance(runtime, str) and bool(runtime)
                and isinstance(row.get('created'), (int, float)) and row['created'] >= created):
            matches.append(row)
    if len(matches) > 1:
        raise OSError('ambiguous exact delivered custody proof')
    return SubmissionObserved(pane, hashlib.sha256(text.encode()).hexdigest()) if matches else None


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
        self.record.pop('submission', None)
        self.record['state'] = 'prepared'
        self.save(self.record)

    def submitted(self, observed, runtime):
        """Persist only positive adapter evidence for this owned body/runtime."""
        from .protocols import SubmissionObserved
        if (self.record is not None and isinstance(observed, SubmissionObserved)
                and observed.matches(self.pane, self.record['text'])
                and isinstance(runtime, str) and runtime):
            self.record['submission'] = dict(pane=observed.pane,
                body_sha256=observed.body_sha256, runtime=runtime)
            self.save(self.record)

    def finish(self, state):
        if self.record is not None:
            self.record['state'] = state
            self.save(self.record)

    def failed(self, panes, *, multiline=False):
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
        if record['session'] is None or triage.mid_flight(screen):
            return
        if '\n' in record['text']:
            if multiline:
                self._clear_multiline(panes, screen)
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

    def _clear_multiline(self, panes, screen):
        """Bounded local recovery; fence every key against session and owned text."""
        from . import input_box, triage
        from .tmux import _codex_owned_input
        record = self.record
        if not _codex_owned_input(screen, record['text']):
            return
        expected = input_box._codex_box(screen)[2]
        for _ in range(81):
            before_length = len(expected)
            for key in ('C-e', 'C-u', 'BSpace'):
                screen = panes.capture(self.pane, attrs=True, timeout=2)
                framed = input_box._codex_box(screen)
                if (framed is None or triage.mid_flight(screen)
                        or input_box._codex_busy(screen)
                        or panes.session_created(self.pane) != record['session']
                        or not panes._confirmed_codex(self.pane, panes.foreground(self.pane))):
                    return
                state, raw, current = framed
                if state in (input_box.EMPTY, input_box.GHOST):
                    self.finish('cleared')
                    return
                if current != expected or not _codex_owned_input(screen, expected):
                    return
                panes.control(self.pane, key)
                if key == 'C-e':
                    continue
                if key == 'C-u':
                    screen, changed = input_box._settle(panes, self.pane, raw)
                else:
                    # Removing a preceding newline is invisible after trim;
                    # _settle's cursor nudge would move to the wrong line.
                    time.sleep(0.15)
                    screen = panes.capture(self.pane, attrs=True, timeout=2)
                after = input_box._codex_box(screen)
                if after is None:
                    return
                if after[0] in (input_box.EMPTY, input_box.GHOST):
                    self.finish('cleared')
                    return
                # Deletion may only retain an unchanged buffer or its prefix.
                # A foreign suffix/race stops before any further editing key.
                remaining = after[2]
                if not expected.startswith(remaining):
                    return
                expected = remaining
            if len(expected) >= before_length:
                return

    def clear_previous(self, panes, screen, *, multiline=False):
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
            self.failed(panes, multiline=multiline)
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
MAX_PENDING_SECONDS = 3600
# aegis-185l. The backlog watch below re-arms only on an EMPTY backlog, which a
# busy agent never reaches, so it fired once on 10-20 and then stayed silent
# while panes were stranded for 3h and 10h. These two conditions are episodic
# on their own evidence, whatever the backlog holds.
STRANDED_SECONDS = 900
FAILED_SENDS = 5


def clear_stalled_owned(root, card, panes, *, states=('superseded', 'queued', 'unknown')):
    """Retire obsolete owned composer text without a board read or submission.

    A superseded notice is excluded from supervise's pending queue. Waiting for
    a later successful send to clear it deadlocks when that occupied composer
    is precisely what prevents the next send. Session and exact-body custody
    remain mandatory; foreign drafts and busy panes are never edited.
    """
    from .tmux import _codex_owned_input
    socket = getattr(panes, 'socket', None)
    screen = panes.capture(card.pane, attrs=True, timeout=2)
    with Custody(root, card.pane, socket) as custody:
        matches = [r for r in custody.records()
                   if r['state'] in states and r['session'] is not None
                   and r['session'] == panes.session_created(card.pane)
                   and _codex_owned_input(screen, r['text'])]
        return len(matches) == 1 and custody.clear_previous(panes, screen, multiline=True)


def clear_superseded(root, card, panes):
    return clear_stalled_owned(root, card, panes, states=('superseded',))


def _end_custody(custody, records, panes, pane, screen, *, phase,
                 card=None, box=None, messages=(), readable=False):
    """Mark records nothing can act on any more; see END_OF_CUSTODY.

    phase 'orphan' runs BEFORE the per-record pointer loop and phase 'dequeue'
    AFTER receipts are read, so a body known to be read is 'acknowledged',
    the more exact end, never 'dequeued'.

    ORPHANING NEVER LOSES A NOTICE (Dearing's review of #445). A dead-session
    body that already has a pointer is orphaned; its pointer carries it. One
    with no pointer is first matched against the unread inbox, as the pointer
    loop would (an inbox delivery's own item IS its pointer). The rest get ONE
    consolidated pointer per agent per pass, not one each (about 4,000 were
    pointerless when this landed), and only then become 'orphaned'. An
    unreadable inbox, or a pointer write whose outcome is unknown, leaves them
    non-terminal; no pointer is ever minted blindly a second time.

    Session identity is read once. An unreadable one decides nothing, and a
    record with no recorded session is left alone. 'dequeued' needs all three
    observations at once: not busy, an empty or placeholder composer, and no
    queue preview carrying this body. A composer holding text decides nothing,
    because joined bodies (aegis-fu2) can hide there.
    """
    from . import triage
    from .tmux import _codex_queue
    try:
        current = panes.session_created(pane)
    except Exception:
        return
    if current is None:
        return
    if phase == 'orphan':
        _orphan(custody, [r for r in records if r['state'] not in TERMINAL
                          and r.get('session') is not None and r['session'] != current],
                card=card, box=box, messages=messages, readable=readable)
        return
    idle_and_empty = (not triage.mid_flight(screen) and triage.input_state(screen)
                      in (triage.INPUT_EMPTY, triage.INPUT_PLACEHOLDER))
    for record in records:
        if (record['state'] == 'queued' and record.get('session') == current
                and idle_and_empty and not _codex_queue(screen)):
            record['state'] = 'dequeued'
            custody.save(record)


ORPHAN_MARKER = '[st delivery orphans '


def _orphan(custody, dead, *, card, box, messages, readable):
    """Dead-session records: end custody only once a pointer carries each."""
    if not dead:
        return
    needs = []
    for record in dead:
        state = record.get('pointer_state')
        marker = record.get('receipt_marker') or ('[st delivery ' + record['id'] + ']')
        if state in ('recorded', 'ambiguous'):
            record['state'] = 'orphaned'
            custody.save(record)
            continue
        if not readable:
            continue                       # UNKNOWN inbox: decide nothing
        matches = [m for m in messages if m.body == record['text'] or marker in m.body]
        if state == 'attempting':
            # A write whose outcome was unknown: accept only proof it landed.
            if len(matches) == 1:
                record.update(pointer=matches[0].id, pointer_state='recorded', state='orphaned')
                custody.save(record)
            continue
        if len(matches) >= 1:
            record['pointer_state'] = 'recorded' if len(matches) == 1 else 'ambiguous'
            if len(matches) == 1:
                record['pointer'] = matches[0].id
            record['receipt_marker'] = marker if marker in matches[0].body else record['text'].rsplit(' ', 1)[0]
            record['state'] = 'orphaned'
            custody.save(record)
            continue
        needs.append(record)
    if not needs or card is None or box is None:
        return
    group = ORPHAN_MARKER + uuid.uuid4().hex + ']'
    for record in needs:                   # persist intent before the board call
        record.update(pointer_state='attempting', receipt_marker=group)
        custody.save(record)
    first = min(needs, key=lambda r: r['created'])
    body = (f'{group} {len(needs)} notice(s) from a previous session of {card.name} were '
            f'never confirmed submitted. Retained bodies under this deployment root, '
            f'e.g. delivery/{first["id"]}.json. Inspect with `st agent input {card.name} --show`.')
    item = box.deliver(card.name, body, frm='st tend')
    if isinstance(messages, list):
        messages.append(item)   # this pass already counts it as unread backlog
    for record in needs:
        record.update(pointer=item.id, pointer_state='recorded', state='orphaned')
        custody.save(record)


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
        _end_custody(custody, observed, panes, card.pane, screen, phase='orphan',
                     card=card, box=box, messages=messages, readable=readable)
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
                # A terminal custody transition below does not read its notice.
                # Count this new unread pointer in the same pass's backlog.
                messages.append(item)
                record['pointer'] = item.id
                record['receipt_marker'] = marker
                record['pointer_state'] = 'recorded'
                custody.save(record)
            pending.append(record)
        # After receipts: a queue the idle pane no longer shows ends custody.
        _end_custody(custody, pending, panes, card.pane, screen, phase='dequeue')
        pending = [r for r in pending if r['state'] not in TERMINAL]

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
        # An unreadable inbox is not an empty one: let a blocked composer page.
        backlog = bool(pending) or bool(messages) or not readable
        _stranded_watch(root, reg, card, panes, socket, screen, observed, now,
                        backlog=backlog)

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
        state = triage.input_state(screen)
        busy = triage.mid_flight(screen)
        # ABSENT/UNKNOWN cannot establish idle or busy. Keep the idle grace
        # separate from an absolute ceiling so any unresolved backlog alarms.
        idle = not busy and state in (triage.INPUT_EMPTY, triage.INPUT_PLACEHOLDER,
                                      triage.INPUT_QUEUED)
        if idle:
            watch.setdefault('idle_since', now)
        else:
            watch.pop('idle_since', None)
        custody.save(watch)
        from .tmux import _codex_queue
        idle_queue = idle and bool(_codex_queue(screen))
        absolute = now - watch['since'] >= MAX_PENDING_SECONDS
        idle_expired = idle and now - watch['idle_since'] >= STALL_SECONDS
        if watch.get('alerted') or not (idle_queue or absolute or idle_expired) or reg is None:
            return
        catalog = deployment_catalog(root)
        recipient = route_stop(reg, card.name, catalog=catalog).to
        observation = ('cannot-tell' if state in (triage.INPUT_ABSENT, triage.INPUT_UNKNOWN)
                       else 'busy' if busy else 'idle' if idle else 'occupied')
        reason = ('idle Codex queue remains unsubmitted' if idle_queue else
                  'absolute pending ceiling' if absolute else 'idle grace expired')
        detail = (f'{card.name}: undelivered inbox/custody: {reason}; '
                  f'observed unresolved for {int(now - watch["since"])}s; box={state}; '
                  f'busy={busy}; observation={observation}; retained={len(pending)}; '
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


def _stranded_watch(root, reg, card, panes, socket, screen, records, now, *, backlog=False):
    """Page the lead when st's own text is stuck in an idle composer for 15 min,
    when ANY text has held an idle composer for 15 min while mail waits, or
    when FAILED_SENDS consecutive sends to the pane were never delivered.

    Each condition is its own episode. The composer episodes re-arm when the
    composer stops holding that text or the pane is seen busy; the send
    episode re-arms after a delivery. No body text enters the alert, and
    nothing here types into the pane.

    THE OCCUPIED EPISODE (aegis-fu2). On 11-01/02 franklin, wu and dearing sat
    idle for hours behind composer text that matched no single custody body
    (INFERRED: Codex handed several queued st bodies back to the composer
    together at turn end). The owned episode needs an exact match, so it never
    armed; the backlog watch had latched in October and never re-armed; and
    every later send was refused occupied-composer. A composer holding text in
    an idle pane while mail waits blocks all delivery whoever wrote it, so it
    pages. It still never clears or submits: unmatched text authorizes no key.
    """
    from . import triage
    from .events import FilesEvents
    from .tier import route_stop, deployment_catalog
    from .tmux import _codex_owned_input
    records = sorted(records, key=lambda r: r['created'])
    owned = None
    busy = triage.mid_flight(screen)
    if not busy:
        owned = next((r for r in records
                      if r['state'] not in ('delivered', 'acknowledged') + END_OF_CUSTODY
                      and _codex_owned_input(screen, r['text'])), None)
    occupied = (owned is None and not busy and backlog
                and triage.input_state(screen) == triage.INPUT_QUEUED)
    last_ok = max((i for i, r in enumerate(records)
                   if r['state'] in ('delivered', 'acknowledged')), default=-1)
    # Queued input has been accepted for a later turn. Its idle backlog is
    # watched above; it is not evidence of consecutive failed submissions.
    # End-of-custody records (aegis-u2s) were never a failed submission to THIS
    # session's pane: a dead session's body, or a queue the pane drained.
    failing = [r for r in records[last_ok + 1:]
               if r['state'] not in ('delivered', 'acknowledged', 'queued') + END_OF_CUSTODY]
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
        held = watch.get('occupied') or {}
        if not occupied:
            watch.pop('occupied', None)
        else:
            held = held or dict(since=now, alerted=False)
            watch['occupied'] = held
            if not held['alerted'] and now - held['since'] >= STRANDED_SECONDS:
                alerts.append((f'composer-occupied:{card.name}:{held["since"]}',
                               f'{card.name}: idle composer has held text matching no single '
                               f'st body for {int(now - held["since"])}s while mail waits; '
                               'st cannot clear or submit it, and every later send is refused'))
                held['alerted'] = True
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
                               f'over {int(now - failing[0]["created"])}s (unconfirmed submissions; '
                               'accepted queues remain pending)'))
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
