"""Normal fleet-tend adapters for the stopped-owner policy; no new producer."""
from __future__ import annotations

import os
import json
import hashlib
from pathlib import Path
import subprocess

from .cycle import lifecycle_lock
from .owned_work import OwnedWork
from .stopped import FilesStops
from .stranded_work import StrandedWork, resume_exempt


def mode():
    value = os.environ.get('SHANTY_STRANDED_WORK', 'off')
    if value not in {'off', 'observe', 'release'}:
        raise ValueError('SHANTY_STRANDED_WORK must be off, observe or release')
    return value


def recipient(name, cards):
    """Resolve the host administrator; in-progress work needs an operator decision."""
    administrators = [c.name for c in cards.values() if c.role == 'administrator']
    if len(administrators) != 1 or administrators[0] == name:
        raise ValueError('stranded owner routing UNKNOWN')
    return administrators[0]


def checkpoint(card):
    """Name the retained workspace/ref without reading private checkpoint text."""
    if card is None or not card.workspace:
        return None
    tree = Path(card.workspace)
    branch = subprocess.run(['git', '-C', str(tree), 'symbolic-ref', '--quiet',
                             '--short', 'HEAD'], capture_output=True, text=True, timeout=5)
    head = subprocess.run(['git', '-C', str(tree), 'rev-parse', '--verify', 'HEAD'],
                         capture_output=True, text=True, timeout=5)
    if head.returncode != 0 or len(head.stdout.strip()) != 40:
        return None
    return dict(worktree=str(tree), branch=branch.stdout.strip() if branch.returncode == 0
                else 'detached@' + head.stdout.strip(), head=head.stdout.strip(),
                checkpoint='Original item notes/comments and existing workspace retained unchanged')


def sweep(root, registry, tracker, panes, inbox, *, now=None):
    selected = mode()
    if selected == 'off':
        return []  # No board, process, stop-store or credential read by default.
    from .deployment import local_host
    host = local_host(root)
    if not host:
        raise ValueError('stranded owner host scope UNKNOWN')
    cards_list = registry.all().exact()
    cards = {card.name: card for card in cards_list}
    if len(cards) != len(cards_list):
        raise ValueError('duplicate crew cards')
    projection = getattr(tracker, 'stranded_rows', None)
    if not callable(projection):
        raise ValueError('stranded work requires complete bounded assignee census')
    local_owners = sorted(name for name, card in cards.items() if card.host == host)
    stop_store = FilesStops(Path(root) / 'stopped')
    service = OwnedWork(root)
    def observe(name, card):
        try:
            actual_card = registry.get(name)
        except LookupError:
            actual_card = None
        if actual_card != card:
            return dict(state='unknown', generation='card changed', resume_at=None)
        if card is not None and card.host != host:
            return dict(state='unknown', generation='owner is not scoped to this host', resume_at=None)
        current = service.snapshot().get(name, {})
        stop = stop_store.all().exact().get(name)
        state = ('missing' if card is None else panes.owner_state(card.pane))
        generation = current.get('generation', 'no-launch-record')
        # A recorded stop plus positive process absence is authoritative;
        # an older cycle refusal must not hide this independently proven class.
        if state == 'down' and stop is not None:
            generation += ':operator-stop:' + hashlib.sha256(json.dumps(
                [stop.at, stop.by, stop.reason, stop.resume_at]).encode()).hexdigest()
            return dict(state='operator-stopped', generation=generation,
                        resume_at=stop.resume_at, intentional_stop=stop.resume_at is None)
        # A refused cycle is a separate positive fact, not inferred from age or
        # a busy pane. Re-read at the CAS fence; changed/refused metadata resets
        # the measured interval. Malformed/unreadable input cannot prove absence.
        from .cycle import Requests, refusal_summary
        path = Requests(root).path
        try:
            if path.exists():
                with path.open('rb') as handle:
                    raw = handle.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ValueError('cycle ledger exceeds bound')
                requests = json.loads(raw)
                if not isinstance(requests, dict):
                    raise ValueError('cycle ledger malformed')
                record = requests.get(name)
                if record is not None and not isinstance(record, dict):
                    raise ValueError('cycle record malformed')
                _, reason = refusal_summary(record)
                if reason:
                    if not isinstance(reason, str):
                        raise ValueError('cycle refusal malformed')
                    state = 'cycle-blocked'
                    generation += ':' + hashlib.sha256(json.dumps(
                        [record.get('requested_at'), reason], sort_keys=True).encode()).hexdigest()
        except (OSError, ValueError, TypeError, AttributeError):
            state = 'unknown'
        return dict(state=state, generation=generation,
                    resume_at=stop.resume_at if stop else None,
                    intentional_stop=stop is not None and stop.resume_at is None)
    def destination(name, current_cards):
        local_cards = {n: c for n, c in current_cards.items() if c.host == host}
        target = recipient(name, local_cards)
        target_card = current_cards.get(target)
        if not target_card or panes.owner_state(target_card.pane) != 'live':
            raise ValueError('administrator delivery liveness UNKNOWN')
        return target
    def notify(target, body, key):
        deliver = getattr(inbox, 'deliver_once', None)
        if not callable(deliver):
            raise ValueError('keyed stranded-owner delivery unsupported')
        receipt = deliver(target, body, key, frm='st stranded-owner')
        seen = inbox.find_delivery(target, key)
        if seen is None or seen.id != receipt.id or seen.body != body:
            raise ValueError('stranded-owner error receipt UNKNOWN')
    read = getattr(tracker, 'stranded_read', None)
    release = getattr(tracker, 'release_stranded', None)
    if selected == 'release' and (not callable(read) or not callable(release)):
        raise ValueError('revision-fenced stranded release unsupported')
    # aegis-ljb: a live owner can produce no finding, and a missing row
    # resolves prior attention exactly as an observed live owner does. So read
    # only owners not observed live, one owner per bounded read. The
    # whole-roster read needed ~64k field rows (6,285 items, mostly inbox
    # pointers) against the fixed 10,000-row plate budget and crashed on
    # every natural pass. Any failed owner read still fails the whole sweep.
    scoped = [name for name in local_owners
              if observe(name, cards[name])['state'] != 'live']
    rows = []
    for name in scoped:
        rows.extend(projection([name]))
    detector = StrandedWork(root)
    # One sweep timestamp joins attention to coverage. Sampling again after
    # tick made natural-clock runs report zero due work despite due findings.
    import time
    measured = time.time() if now is None else now
    result = detector.tick(rows, cards, observe=observe, recipient=destination,
        notify=notify, read=read, release=release,
        checkpoint=lambda name, card: checkpoint(card),
        fence=lambda name: lifecycle_lock(root, name), now=measured,
        release_admitted=selected == 'release', operator_release_only=True)
    # The already deployed held-work reader joins these lifecycle observations
    # to assigned work. No second brief board scan or private checkpoint payload.
    findings = detector.snapshot()
    # The complete read includes inbox pointers for honest coverage accounting;
    # their recipient assignments are never work-release candidates.
    from .files import write_json_atomic
    from .inbox import is_message
    census = {name: dict(work=0, inbox=0, release_due=0) for name in scoped}
    for row in rows:
        name = (row.get('assignee') or '').rsplit('/', 1)[-1]
        counts = census.setdefault(name, dict(work=0, inbox=0, release_due=0))
        message = is_message(row.get('title', ''))
        counts['inbox' if message else 'work'] += 1
        finding = findings.get(row['id'], {})
        if (not message and finding.get('checked_at') == measured
                and finding.get('evidence') == 'operator-stopped'
                and finding.get('release_due')):
            counts['release_due'] += 1
    write_json_atomic(detector.root / 'census.json',
                      dict(checked_at=measured, complete=True,
                           scope='local owners not observed live',
                           owners=census,
                           live_unread=sorted(set(local_owners) - set(scoped))))
    for name in {entry['owner'] for entry in findings.values()}:
        card = cards.get(name)
        evidence = observe(name, card)
        if evidence['state'] == 'live':
            service.confirmed_live(name, now=measured)
        elif any(entry.get('active') and entry.get('attention') and entry['owner'] == name
                 for entry in findings.values()):
            if evidence['state'] in {'down', 'missing', 'cycle-blocked'} and not evidence.get('intentional_stop') and not resume_exempt(evidence['resume_at'], measured):
                service.confirmed_down(name, now=measured,
                    reason=('confirmed cycle refusal; stranded work' if evidence['state'] == 'cycle-blocked'
                            else 'confirmed process absence; stranded work'))
    return result
