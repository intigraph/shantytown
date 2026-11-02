"""Normal fleet-tend adapters for the stopped-owner policy; no new producer."""
from __future__ import annotations

import os
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
    """Follow the actual crew card; unreachable leads rise to administrator."""
    card = cards.get(name)
    lead = cards.get(card.reports_to) if card else None
    if lead is not None and lead.name != name:
        return lead.name
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
    projection = getattr(tracker, 'ranking_rows', None)
    packet = projection() if callable(projection) else None
    if packet is None:
        raise ValueError('stranded work requires complete bounded owner projection')
    _, rows = packet
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
        return dict(state=state, generation=current.get('generation', 'no-launch-record'),
                    resume_at=stop.resume_at if stop else None)
    def destination(name, current_cards):
        local_cards = {n: c for n, c in current_cards.items() if c.host == host}
        target = recipient(name, local_cards)
        target_card = current_cards.get(target)
        if target_card and target_card.role != 'administrator':
            status = panes.owner_state(target_card.pane)
            if status == 'down':
                return recipient(target, local_cards)
            if status != 'live':
                raise ValueError('lead delivery liveness UNKNOWN')
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
    detector = StrandedWork(root)
    result = detector.tick(rows, cards, observe=observe, recipient=destination,
        notify=notify, read=read, release=release,
        checkpoint=lambda name, card: checkpoint(card),
        fence=lambda name: lifecycle_lock(root, name), now=now,
        release_admitted=selected == 'release')
    # The already deployed held-work reader joins these lifecycle observations
    # to assigned work. No second brief board scan or private checkpoint payload.
    import time
    measured = time.time() if now is None else now
    findings = detector.snapshot()
    for name in {entry['owner'] for entry in findings.values()}:
        card = cards.get(name)
        evidence = observe(name, card)
        if evidence['state'] == 'live':
            service.confirmed_live(name, now=measured)
        elif any(entry.get('active') and entry.get('attention') and entry['owner'] == name
                 for entry in findings.values()):
            if evidence['state'] in {'down', 'missing'} and not resume_exempt(evidence['resume_at'], measured):
                service.confirmed_down(name, now=measured)
    return result
