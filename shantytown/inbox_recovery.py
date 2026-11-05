"""Submit an existing durable inbox body only when Codex still displays it.

# arming: library; invoked by the scheduled tend pass, never an agent wake.
"""
from __future__ import annotations
import time

from .tmux import PaneSubmissionUnverified, _codex_owned_input
from . import triage


def sweep(agents, panes, box, *, root=None, reg=None, log=lambda message: None):
    recovered = []
    agents = list(agents)
    if root is not None:
        # Clear obsolete locally owned notices BEFORE slow tracker reads. A
        # single 30s inbox timeout otherwise consumes the whole 25s budget and
        # the dispatcher near the end of the roster is never examined.
        from .delivery import clear_stalled_owned
        for card in agents:
            if getattr(card, 'retired', False) or not card.pane:
                continue
            try:
                if (panes.exists(card.pane)
                        and panes._confirmed_codex(card.pane, panes.foreground(card.pane))
                        and clear_stalled_owned(root, card, panes)):
                    log(f'inbox recovery: {card.name} cleared stalled owned text; custody retained, not submitted')
            except Exception as exc:
                log(f'inbox recovery: {card.name} local custody UNKNOWN ({type(exc).__name__})')
        # Rotate the expensive observations across ticks. A slow first member
        # must not starve every later member indefinitely.
        from pathlib import Path
        from .files import write_json_atomic
        cursor = Path(root) / 'notify' / 'inbox_recovery_cursor.json'
        import json
        try:
            previous = json.loads(cursor.read_text()).get('next', '')
        except (OSError, ValueError):
            previous = ''
        names = [card.name for card in agents]
        start = names.index(previous) if previous in names else 0
        agents = agents[start:] + agents[:start]
    # One observation budget for the whole fleet, not 25 seconds per strand.
    deadline = time.monotonic() + 25
    for card in agents:
        if time.monotonic() >= deadline:
            log('inbox recovery: observation budget exhausted; remaining pointers retained')
            break
        if root is not None and agents:
            next_card = agents[(agents.index(card) + 1) % len(agents)]
            cursor.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(cursor, {'next': next_card.name})
        if getattr(card, 'retired', False) or not card.pane:
            continue
        try:
            if not panes.exists(card.pane):
                continue
            if not panes._confirmed_codex(card.pane, panes.foreground(card.pane)):
                continue
            screen = panes.capture(card.pane, attrs=True, timeout=2)
            if root is not None:
                from .delivery import supervise
                supervise(root, reg, card, panes, box, screen, deadline=deadline)
                continue
            if triage.input_state(screen) in (triage.INPUT_EMPTY, triage.INPUT_PLACEHOLDER):
                continue
            matches = [msg for msg in box.unread(card.name)
                       if _codex_owned_input(screen, msg.body)]
            # Ambiguous duplicate pointers are not permission to submit twice.
            if len(matches) != 1:
                continue
            msg = matches[0]
            # submit_owned rechecks runtime and exact ownership before any
            # key. A changed composer must never authorize typing our body.
            panes.submit_owned(card.pane, msg.body, deadline=deadline)
            box.mark_read(card.name, ids=[msg.id])
            recovered.append((card.name, msg.id))
            log(f'inbox recovery: {card.name} submitted {msg.id}')
        except PaneSubmissionUnverified as exc:
            log(f'inbox recovery: {card.name} stranded input: {exc}')
        except Exception as exc:
            # Read or submission UNKNOWN keeps the pointer open. No resend.
            log(f'inbox recovery: {card.name} UNKNOWN ({type(exc).__name__})')
    return recovered
