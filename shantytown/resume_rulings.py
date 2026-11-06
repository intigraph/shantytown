"""Typed, post-deferral controller comments; prose never discharges a gate."""
from __future__ import annotations

from datetime import timedelta
import re

from .deferral_notes import PROVENANCE_PREFIX, parse_provenance
from .deferrals import parse_stamp

KINDS = ('ruling', 'activation')
BUDGET_DEFERRED = 'typed ruling observation deferred by read budget'
ITEM = re.compile(r'[a-z][a-z0-9-]{1,79}(?:\.[0-9]+)*')
STAMP = r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z'
MARKER = re.compile(r'resume-event-v1: (ruling|activation):(' + ITEM.pattern +
                    r') outcome=(granted|denied|revoked) authority=([a-z][a-z0-9-]{0,63}) at=(' + STAMP + r')')
MAX_COMMENTS = 1000
MAX_BYTES = 2_000_000


def validate(kind, item):
    if kind not in KINDS or not isinstance(item, str) or not ITEM.fullmatch(item):
        raise ValueError('expected ruling:<item> or activation:<item>')


def boundary(waiting, now):
    """Current canonical deferral provenance, never dateModified or free prose."""
    lines = [line for line in str(waiting.get('notes') or '').splitlines()
             if line.lstrip().startswith(PROVENANCE_PREFIX.rstrip(': '))]
    if len(lines) != 1:
        raise ValueError('deferral provenance is missing or ambiguous')
    value = parse_provenance(lines[0])
    if value is None:
        raise ValueError('deferral provenance is invalid')
    start, end = parse_stamp(value['set_at']), parse_stamp(value['until'])
    if (start is None or end is None or start > now or end <= start
            or end != parse_stamp(waiting.get('defer_until'))):
        raise ValueError('deferral boundary does not match current wait')
    return start


def authorities(target, registry):
    """Authority comes from complete crew cards, not from the marker's claim."""
    crew = registry.all().exact()
    cards = {agent.name: agent for agent in crew}
    if len(cards) != len(crew):
        raise ValueError('crew card identities are ambiguous')
    admins = [agent.name for agent in crew if agent.role == 'administrator']
    if len(admins) != 1:
        raise ValueError('configured administrator is UNKNOWN')
    owner = target.get('assignee')
    if not isinstance(owner, str) or not owner:
        raise ValueError('target item owner/lead is UNKNOWN')
    card = cards.get(owner)
    if card is None:
        raise ValueError('owner card identity is UNKNOWN')
    allowed = set(admins)
    if card.reports_to:
        lead = cards.get(card.reports_to)
        if lead is None or lead.role not in ('lead', 'administrator'):
            raise ValueError('configured item lead is UNKNOWN')
        allowed.add(lead.name)
    elif card.role != 'administrator':
        raise ValueError('item lead is not configured')
    return allowed


def evaluate(kind, item, waiting, now, *, show, comments, registry):
    """Latest exact authorized post-boundary outcome; a denial stays held."""
    stage = 'binding'
    try:
        validate(kind, item)
        start = boundary(waiting, now)
        stage = 'target'
        target = show(item)
        if not isinstance(target, dict) or target.get('id') != item:
            raise ValueError('target identity is UNKNOWN')
        stage = 'registry'
        allowed = authorities(target, registry)
        stage = 'comments'
        rows = comments(item)
        if (not isinstance(rows, list) or len(rows) >= MAX_COMMENTS
                or any(not isinstance(row, dict) for row in rows)
                or sum(len(str(row.get('text') or '').encode()) for row in rows) > MAX_BYTES):
            raise ValueError('comment inventory is incomplete or capped')
        stage = 'markers'
        evidence = []
        seen = set()
        for row in rows:
            text = row.get('text')
            if not isinstance(text, str):
                raise ValueError('comment text is unreadable')
            markers = [line for line in text.splitlines() if line.startswith('resume-event-v1:')]
            if not markers:
                continue
            recorded = parse_stamp(row.get('created_at'))
            if recorded is None:
                raise ValueError('typed comment creation time is UNKNOWN')
            if recorded <= start:
                continue  # historical malformed markers do not gate a new wait
            for line in markers:
                match = MARKER.fullmatch(line)
                if match is None:
                    raise ValueError('typed comment marker is malformed')
                found_kind, found_item, outcome, authority, declared = match.groups()
                if (found_kind, found_item) != (kind, item):
                    continue
                at = parse_stamp(declared)
                if recorded is None or at is None:
                    raise ValueError('typed comment timestamp is UNKNOWN')
                # An old comment cannot be made fresh by quoting a new time.
                if recorded <= start or at <= start:
                    continue
                if (row.get('author') != authority or authority not in allowed
                        or not start < at <= recorded <= now
                        or recorded - at > timedelta(minutes=5)):
                    raise ValueError('typed comment authority/time is not admissible')
                if type(row.get('id')) is not int or row['id'] < 1:
                    raise ValueError('typed comment identity is UNKNOWN')
                if row['id'] in seen:
                    raise ValueError('typed comment identity is duplicated')
                seen.add(row['id'])
                evidence.append((recorded, row['id'], outcome))
        if not evidence:
            return False, 'no exact authorized post-deferral marker observed'
        evidence.sort()
        last = evidence[-1]
        if any(row[:2] == last[:2] and row[2] != last[2] for row in evidence):
            raise ValueError('typed comment outcome is ambiguous')
        return last[2] == 'granted', 'latest exact authorized outcome is ' + last[2]
    except Exception:
        # Registry/store failures stay UNKNOWN. No raw comment/private transport
        # text is exposed, and no read failure can release a runtime gate.
        return None, f'typed ruling evidence is UNKNOWN; retain hold; reason={stage}'
