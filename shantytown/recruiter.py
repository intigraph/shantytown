"""Protected scope for event-driven review/merge recruiters.

This capability is deliberately separate from administrator role membership.
Only the operator-owned policy and authenticated Unix principal can supply it.
No environment variable selects the policy, identity, repositories or verbs.
Loading a scope does not admit a job: exact-head authority and normal spawn
holds/governor/cap/quiet-time gates still apply at the controller boundary.
"""
from __future__ import annotations

import json
import os
import re
import sys
import socket
from dataclasses import dataclass
from pathlib import Path

from .actor_identity import IdentityError, authenticated_actor
from .job_launch import protected

POLICY_PATH = (Path('/Library/Application Support/Shantytown/recruiters.json')
               if sys.platform == 'darwin' else Path('/etc/shantytown/recruiters.json'))


@dataclass(frozen=True)
class Scope:
    principal: str
    uid: int
    root: str
    host: str
    repos: tuple[str, ...]
    jobs: tuple[str, ...]

    def check(self, request, *, root, host):
        if (host != self.host or socket.gethostname() != self.host
                or request.job == "merge"
                or str(Path(root).resolve()) != self.root
                or request.repo not in self.repos or request.job not in self.jobs
                or request.checkout is not None or request.harness is not None
                or request.request_id is not None
                or not re.fullmatch(r'[0-9a-f]{40}', request.head or '')
                or type(request.pr) is not int or request.pr < 1
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', request.item or '')):
            raise IdentityError('recruitment request is outside protected scope')


def _scope(data, *, principal, uid, root, host):
    if (not isinstance(data, dict) or set(data) != {'version', 'principals'}
            or type(data['version']) is not int or data['version'] != 1
            or not isinstance(data['principals'], dict)):
        raise IdentityError('invalid recruiter policy')
    row = data['principals'].get(principal)
    if (not isinstance(row, dict) or set(row) != {'uid', 'root', 'host', 'repos', 'jobs'}
            or type(row['uid']) is not int or row['uid'] < 10000 or row['uid'] != uid
            or not isinstance(row['root'], str) or not Path(row['root']).is_absolute()
            or row['root'] != str(Path(root).resolve())
            or not isinstance(row['host'], str) or not row['host'] or row['host'] != host
            or not isinstance(row['repos'], list) or not row['repos']
            or not all(isinstance(repo, str) and re.fullmatch(r'intigraph/[A-Za-z0-9_.-]+', repo)
                       and repo.split('/')[1] not in ('.', '..') for repo in row['repos'])
            or not isinstance(row['jobs'], list) or not row['jobs']
            or not all(job in ('review', 'merge') for job in row['jobs'])):
        raise IdentityError('recruiter has no valid protected UID/root/repository/job scope')
    return Scope(principal, uid, row['root'], row['host'], tuple(row['repos']), tuple(row['jobs']))


def load(*, root, host):
    """Read only fixed protected policy; missing policy grants no capability."""
    if not POLICY_PATH.exists():
        return None
    protected(POLICY_PATH)
    if POLICY_PATH.stat().st_size > 1024 * 1024:
        raise IdentityError('recruiter policy exceeds limit')
    principal = authenticated_actor()
    if not principal:
        raise IdentityError('recruiter requires authenticated protected UID identity')
    try:
        data = json.loads(POLICY_PATH.read_bytes())
    except (ValueError, OSError) as error:
        raise IdentityError('recruiter policy unreadable') from error
    return _scope(data, principal=principal, uid=os.geteuid(), root=root, host=host)


def check_binding(request, record):
    """Use only the existing native work-request record, never PR prose."""
    if not isinstance(record, dict) or record.get('schema') != 'chaski.github.work-request/v1':
        raise IdentityError('recruitment custody record is absent or malformed')
    facts = record.get('facts')
    if not isinstance(facts, dict):
        raise IdentityError('recruitment custody facts are malformed')
    number = facts.get('pr', record.get('subject'))
    if isinstance(number, str):
        number = number.removeprefix('pr/')
        number = int(number) if number.isascii() and number.isdecimal() else None
    if (type(number) is not int or number != request.pr
            or record.get('repo') != request.repo
            or record.get('revision') != request.head
            or record.get('kind') != request.job):
        raise IdentityError('native work request does not bind this exact PR/head/job')


def check_checks(request, runs, statuses, required):
    """Bounded REST inventories; missing protection or partial pages refuse."""
    if (not isinstance(runs, dict) or type(runs.get('total_count')) is not int
            or not isinstance(runs.get('check_runs'), list)
            or runs['total_count'] != len(runs['check_runs']) or not runs['check_runs']
            or not isinstance(statuses, dict) or statuses.get('sha') != request.head
            or type(statuses.get('total_count')) is not int
            or not isinstance(statuses.get('statuses'), list)
            or statuses['total_count'] != len(statuses['statuses'])
            or not isinstance(required, dict) or not isinstance(required.get('contexts'), list)
            or not all(isinstance(name, str) and name for name in required['contexts'])):
        raise IdentityError('required-check inventory is absent, malformed or incomplete')
    observed = set()
    for check in runs['check_runs']:
        if (not isinstance(check, dict) or check.get('head_sha') != request.head
                or not isinstance(check.get('name'), str) or not check['name']
                or check.get('status') != 'completed' or check.get('conclusion') != 'success'):
            raise IdentityError('exact-head checks are not complete green')
        observed.add(check['name'])
    for status in statuses['statuses']:
        if (not isinstance(status, dict) or status.get('state') != 'success'
                or not isinstance(status.get('context'), str) or not status['context']):
            raise IdentityError('exact-head commit statuses are not green')
        observed.add(status['context'])
    if not set(required['contexts']).issubset(observed):
        raise IdentityError('a required check is absent on this head')
    specs = required.get('checks', [])
    if not isinstance(specs, list):
        raise IdentityError('required app checks are malformed')
    for spec in specs:
        if (not isinstance(spec, dict) or not isinstance(spec.get('context'), str)
                or spec['context'] not in observed):
            raise IdentityError('required app check is absent')
        app = spec.get('app_id')
        if app not in (None, -1) and (type(app) is not int or not any(
                check['name'] == spec['context'] and isinstance(check.get('app'), dict)
                and check['app'].get('id') == app for check in runs['check_runs'])):
            raise IdentityError('required check app identity does not match')


def admit(request, *, gh, verdict, binding):
    """Fresh exact-head admission. gh/verdict/binding are controller adapters.

    All calls are bounded reads; errors propagate to terminal UNKNOWN in the
    caller's attempt ledger. No returned event payload is used as authority.
    """
    from urllib.parse import quote
    check_binding(request, binding(request.item))
    path = f'repos/{request.repo}/pulls/{request.pr}'
    info = gh(path)
    if (not isinstance(info, dict) or info.get('state') != 'open' or info.get('draft') is not False
            or info.get('number') != request.pr
            or (info.get('head') or {}).get('sha') != request.head
            or ((info.get('head') or {}).get('repo') or {}).get('full_name') != request.repo
            or ((info.get('base') or {}).get('repo') or {}).get('full_name') != request.repo
            or info.get('author_association') not in ('OWNER', 'MEMBER', 'COLLABORATOR')
            or not isinstance(info.get('node_id'), str) or not info['node_id']
            or not isinstance((info.get('base') or {}).get('ref'), str)):
        raise IdentityError('PR is outside internal open exact-head recruitment scope')
    base = quote(info['base']['ref'], safe='')
    required = gh(f'repos/{request.repo}/branches/{base}/protection/required_status_checks')
    runs = gh(f'repos/{request.repo}/commits/{request.head}/check-runs?per_page=100')
    statuses = gh(f'repos/{request.repo}/commits/{request.head}/status?per_page=100')
    check_checks(request, runs, statuses, required)
    decision = verdict(request.repo, request.pr, info['node_id'], request.head)
    if (not isinstance(decision, dict) or decision.get('author_agent_unknown') is not False
            or not isinstance(decision.get('approvals'), list)
            or not isinstance(decision.get('blocking'), list)):
        raise IdentityError('authoritative non-author verdict state is unknown')
    if decision['approvals'] or decision['blocking']:
        raise IdentityError('this head already has a non-author verdict')
    # Re-read custody and head after the independent reads, before any spawn.
    check_binding(request, binding(request.item))
    latest = gh(path)
    if (latest.get('state') != 'open' or latest.get('draft') is not False
            or (latest.get('head') or {}).get('sha') != request.head):
        raise IdentityError('PR changed during recruitment admission')


def cli_admit(request, *, policy, gh, quipu, binding):
    """Keep the scoped CLI adapter outside the shared spawn lifecycle code."""
    import subprocess
    from . import ephemeral, gate_verdict as gv
    try:
        if not policy.verdict_graph:
            raise IdentityError('recruiter verdict_graph is not configured')
        def authoritative_verdict(repo, pr, node, head):
            return gv.approval(quipu(), repo=repo, pr=pr, node_id=node,
                               head=head, graph=policy.verdict_graph,
                               signers=gv.trusted_signers())
        admit(request, gh=gh, verdict=authoritative_verdict, binding=binding)
    except (IdentityError, gv.VerdictError, OSError, ValueError, TypeError,
            AttributeError, KeyError, subprocess.SubprocessError) as error:
        raise ephemeral.Refused('scoped recruitment admission unproved: ' + type(error).__name__) from None
