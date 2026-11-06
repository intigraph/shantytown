"""Bounded read-only forge facts. A terminal CI event is NOT a green verdict.

Unlike resume_events' per-item natural-pair producer contracts, these kinds
name ordinary forge records. Arguments never choose an executable or host.
Missing, malformed, capped or failed reads remain UNKNOWN and retain the wait.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request
from urllib.parse import urlsplit

KINDS = ('pr-merged', 'ci-terminal')
MAX_BYTES = 2_000_000
PAGE = 100
STATUS_PAGES = 3
MAX_READS = 12
TIMEOUT = 15
REPO = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}'
PR = re.compile(r'(github|forgejo)/(' + REPO + r')#([1-9][0-9]{0,9})')
CI = re.compile(r'(github|forgejo)/(' + REPO + r')@([0-9a-f]{40}|[0-9a-f]{64})')
BUDGET_DEFERRED = 'forge event request budget exhausted; waiting for a scheduled turn'


class BudgetDeferred(ValueError):
    """Not observed this turn; not a failed transport or malformed response."""


def validate(kind, arg):
    pattern = PR if kind == 'pr-merged' else CI if kind == 'ci-terminal' else None
    match = pattern.fullmatch(arg) if pattern is not None and isinstance(arg, str) else None
    if match is None:
        raise ValueError('expected pr-merged:<github|forgejo>/<owner>/<repo>#<number> '
                         'or ci-terminal:<github|forgejo>/<owner>/<repo>@<full-sha>')
    forge, repo, identity = match.groups()
    if any(part in ('.', '..') for part in repo.split('/')):
        raise ValueError('invalid forge repository')
    return forge, repo, identity


class Reader:
    """One phase budget, shared across all selected rows by the caller."""
    def __init__(self):
        self.remaining = MAX_READS

    def __call__(self, forge, repo, path):
        if self.remaining <= 0:
            raise BudgetDeferred(BUDGET_DEFERRED)
        self.remaining -= 1
        if forge == 'github':
            out = subprocess.run(['gh', 'api', '--method', 'GET', 'repos/' + repo + '/' + path],
                                 capture_output=True, text=True, timeout=TIMEOUT, check=False)
            if out.returncode or len(out.stdout.encode()) > MAX_BYTES:
                raise ValueError('GitHub event read failed or exceeded its bound')
            return json.loads(out.stdout)
        # Deployment configuration selects the server; item text cannot select it.
        base = os.environ.get('SHANTY_FORGEJO_URL') or os.environ.get('FORGEJO_URL')
        if not base or urlsplit(base).scheme not in ('http', 'https'):
            raise ValueError('Forgejo server is not configured')
        if urlsplit(base).username or urlsplit(base).password:
            raise ValueError('Forgejo URL must not contain credentials')
        token = os.environ.get('SHANTY_FORGEJO_TOKEN', '')
        if not token:
            token = Path(os.environ.get('FORGEJO_TOKEN_FILE', '~/.forgejo_token')).expanduser().read_text().strip()
        if not token:
            raise ValueError('Forgejo credential is unavailable')
        req = urllib.request.Request(base.rstrip('/') + '/api/v1/repos/' + repo + '/' + path,
                                     method='GET', headers={'Accept': 'application/json',
                                                          'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Forgejo event read exceeded its bound')
        return json.loads(raw)


def _rows(read, forge, repo, path, key=None):
    sep = '&' if '?' in path else '?'
    if key is None:
        # Forgejo's commit-status endpoint caps pages at fifty even when a
        # larger limit is requested. A short *hundred*-row page is not proof
        # of completion there. Keep bounded pagination inside Reader's shared
        # request budget, and refuse repeated pages or a capped inventory.
        size = 50 if forge == 'forgejo' else PAGE
        rows, seen = [], set()
        for page in range(1, STATUS_PAGES + 1):
            doc = read(forge, repo, path + sep + f'per_page={size}&limit={size}&page={page}')
            if (not isinstance(doc, list) or len(doc) > size
                    or any(not isinstance(row, dict) for row in doc)):
                raise ValueError('status inventory is unreadable')
            for row in doc:
                identity = row.get('id')
                if type(identity) is not int or identity in seen:
                    raise ValueError('status inventory repeats or lacks identity')
                seen.add(identity)
                rows.append(row)
            if len(doc) < size:
                return rows
        raise ValueError('status inventory reached its page bound')
    doc = read(forge, repo, path + sep + f'per_page={PAGE}&limit={PAGE}&page=1')
    rows = doc.get(key) if key and isinstance(doc, dict) else doc if not key else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('forge event inventory is unreadable')
    # No unbounded pagination or truncated success. A full page needs a later,
    # explicitly budgeted reader implementation, never an absence inference.
    if len(rows) >= PAGE:
        raise ValueError('forge event inventory reached its page bound')
    if key and ('total_count' not in doc or type(doc['total_count']) is not int
                or doc['total_count'] != len(rows)):
        raise ValueError('forge event inventory completeness is UNKNOWN')
    return rows


def _ci(forge, repo, sha, read):
    runs = _rows(read, forge, repo, 'actions/runs?head_sha=' + sha, 'workflow_runs')
    latest = {}
    for row in runs:
        if row.get('head_sha', row.get('commit_sha')) != sha:
            raise ValueError('workflow event names a different head')
        # Forgejo's event is a legacy payload field, sometimes empty or
        # 'push' for a scheduled/dispatched run. trigger_event is its native
        # run identity; GitHub uses event. Retain legacy fixture/API support
        # only when the native field is absent, never when malformed.
        event = (row.get('trigger_event', row.get('event'))
                 if forge == 'forgejo' else row.get('event'))
        workflow = row.get('workflow_id')
        if (type(row.get('id')) is not int
                or type(workflow) not in (str, int) or not workflow
                or not isinstance(event, str) or not event):
            raise ValueError('workflow identity is unreadable')
        key = ('run', workflow, event)
        if key not in latest or row['id'] > latest[key]['id']:
            latest[key] = row
    active, count = False, 0
    for row in latest.values():
        count += 1
        state = row.get('status')
        conclusion = row.get('conclusion')
        if forge == 'forgejo' and state in ('success', 'failure', 'cancelled', 'skipped'):
            conclusion, state = state, 'completed'
        if forge == 'forgejo' and state == 'running':
            state = 'in_progress'
        if state not in ('completed', 'queued', 'in_progress', 'waiting', 'pending', 'requested'):
            raise ValueError('workflow state is unreadable')
        if state == 'completed' and (not isinstance(conclusion, str) or not conclusion):
            raise ValueError('completed workflow has no conclusion')
        active |= state != 'completed'
    if active:
        # A validated, complete workflow inventory containing an active run
        # already disproves terminal CI. No later status/check read can turn
        # that into MET. Save those requests for other waiting principals.
        return False, 'exact-head CI is still active'
    statuses = _rows(read, forge, repo, 'commits/' + sha + '/statuses')
    checks = (_rows(read, forge, repo, 'commits/' + sha + '/check-runs?filter=latest', 'check_runs')
              if forge == 'github' else [])
    seen_checks = set()
    for row in checks:
        if row.get('head_sha') != sha or type(row.get('id')) is not int or row['id'] in seen_checks:
            raise ValueError('check event identity is unreadable')
        seen_checks.add(row['id'])
        state = row.get('status')
        if state not in ('completed', 'queued', 'in_progress', 'waiting', 'pending', 'requested'):
            raise ValueError('check event state is unreadable')
        if state == 'completed' and (not isinstance(row.get('conclusion'), str) or not row['conclusion']):
            raise ValueError('completed check has no conclusion')
        count += 1
        active |= state != 'completed'
    latest_statuses = {}
    for row in statuses:
        if type(row.get('id')) is not int or not isinstance(row.get('context'), str) or not row['context']:
            raise ValueError('status event identity is unreadable')
        context = row['context']
        if context not in latest_statuses or row['id'] > latest_statuses[context]['id']:
            latest_statuses[context] = row
    for row in latest_statuses.values():
        state = row.get('state', row.get('status'))
        if state not in ('success', 'failure', 'error', 'pending'):
            raise ValueError('status event state is unreadable')
        count += 1
        active |= state == 'pending'
    if not count:
        return None, 'no CI records observed for the exact head'
    return not active, 'exact-head CI is still active' if active else 'observed CI is terminal (any conclusion; not approval)'


def evaluate(kind, arg, read=None):
    try:
        forge, repo, identity = validate(kind, arg)
        read = read or Reader()
        if kind == 'ci-terminal':
            return _ci(forge, repo, identity, read)
        doc = read(forge, repo, 'pulls/' + identity)
        if (not isinstance(doc, dict) or type(doc.get('number')) is not int
                or doc['number'] != int(identity) or type(doc.get('merged')) is not bool
                or doc.get('state') not in ('open', 'closed')):
            raise ValueError('PR event identity/state is unreadable')
        if doc['merged']:
            if doc['state'] != 'closed' or not isinstance(doc.get('merged_at'), str) or not doc['merged_at']:
                raise ValueError('merged PR event is incomplete')
            return True, 'exact PR is merged'
        return False, 'exact PR is not merged (closed is not merged)'
    except BudgetDeferred:
        return None, BUDGET_DEFERRED
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        # Never include transport output/URLs/credentials in the item or logs.
        return None, 'forge event read failed, incomplete or invalid; retain hold'
