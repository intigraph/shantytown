"""Submit an existing durable inbox body only when Codex still displays it.

# arming: library; invoked by the scheduled tend pass, never an agent wake.
"""
from __future__ import annotations

from .tmux import PaneSubmissionUnverified, _codex_owned_input
from . import triage


def sweep(agents, panes, box, *, log=lambda message: None):
    recovered = []
    for card in agents:
        if getattr(card, 'retired', False) or not card.pane:
            continue
        try:
            if not panes.exists(card.pane):
                continue
            if not panes._confirmed_codex(card.pane, panes.foreground(card.pane)):
                continue
            screen = panes.capture(card.pane, attrs=True, timeout=2)
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
            panes.submit_owned(card.pane, msg.body)
            box.mark_read(card.name, ids=[msg.id])
            recovered.append((card.name, msg.id))
            log(f'inbox recovery: {card.name} submitted {msg.id}')
        except PaneSubmissionUnverified as exc:
            log(f'inbox recovery: {card.name} stranded input: {exc}')
        except Exception as exc:
            # Read or submission UNKNOWN keeps the pointer open. No resend.
            log(f'inbox recovery: {card.name} UNKNOWN ({type(exc).__name__})')
    return recovered
