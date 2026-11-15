"""Qualified transport ports for the one shared reminder/ACK consumer.

Fleet sweeps and exact-target reactions share these ports and the same ledger.
No new sender, schedule, backend selection or notification policy lives here.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import copy
from functools import cached_property
from io import StringIO
import re

from .overdue import PendingReceipt

CONTRACT = 'shared-reminder-ports/v1'


class ReminderPorts:
    def __init__(self, tracker, registry, inbox, persist):
        self._tracker, self._registry = tracker, registry
        self._inbox, self._persist = inbox, persist

    @cached_property
    def tracker(self):
        return self._tracker()

    @cached_property
    def registry(self):
        return self._registry()

    @cached_property
    def inbox(self):
        result = self._inbox()
        if not callable(getattr(result, 'find_delivery_receipt', None)):
            raise ValueError('shared reminder exact receipt reader unavailable')
        return result

    def receipt(self, recipient, marker, identifier=None):
        if identifier is None:
            candidate = self.inbox.find_delivery(recipient, marker)
            if candidate is None:
                return None
            identifier = candidate.id
        value = self.inbox.find_delivery_receipt(recipient, marker, identifier)
        if value is None:
            return None
        if (value.id != identifier or value.to not in (recipient, recipient.split('/')[-1])
                or not isinstance(value.body, str) or not value.body.startswith(marker + ' ')):
            raise ValueError('exact shared reminder receipt UNKNOWN')
        return identifier

    def deliver(self, recipient, marker, body, *, boundary_only=False):
        identifier = self._persist(recipient, marker + ' ' + body, boundary_only=boundary_only)
        if identifier is None:
            return None
        try:
            confirmed = self.receipt(recipient, marker, identifier)
            return confirmed if confirmed is not None else PendingReceipt(identifier)
        except Exception:
            # The original send already has an exact ID. Preserve it even if
            # its read-back is unavailable; never infer absence or send again.
            return PendingReceipt(identifier)


def bind(args, panes):
    """Reuse the CLI's selected tracker, registry and durable inbox transport."""
    from . import cli

    def persist(recipient, body, *, boundary_only):
        target = copy(args)
        target.agent, target.dry_run = recipient, False
        output = StringIO()
        with redirect_stdout(output):
            code = cli._inbox_durable(target, ports.registry.get(recipient), body, panes,
                                      sender='st fleet tend', boundary_only=boundary_only)
        if code != cli.OK:
            return None
        match = re.search(r'delivered to inbox as ([A-Za-z0-9_.-]+)', output.getvalue())
        if match is None:
            raise ValueError('known reminder receipt ID unavailable')
        return match[1]

    ports = ReminderPorts(lambda: cli._tracker(args, default='beads'),
                          lambda: cli._registry(args),
                          lambda: cli._inbox(args, default='beads'), persist)
    return ports
