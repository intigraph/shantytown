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
    repos: tuple[str, ...]
    jobs: tuple[str, ...]

    def check(self, request, *, root):
        if (str(Path(root).resolve()) != self.root
                or request.repo not in self.repos or request.job not in self.jobs
                or request.checkout is not None or request.harness is not None
                or request.request_id is not None
                or not re.fullmatch(r'[0-9a-f]{40}', request.head or '')
                or type(request.pr) is not int or request.pr < 1
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', request.item or '')):
            raise IdentityError('recruitment request is outside protected scope')


def _scope(data, *, principal, uid, root):
    if (not isinstance(data, dict) or set(data) != {'version', 'principals'}
            or type(data['version']) is not int or data['version'] != 1
            or not isinstance(data['principals'], dict)):
        raise IdentityError('invalid recruiter policy')
    row = data['principals'].get(principal)
    if (not isinstance(row, dict) or set(row) != {'uid', 'root', 'repos', 'jobs'}
            or type(row['uid']) is not int or row['uid'] < 10000 or row['uid'] != uid
            or not isinstance(row['root'], str) or not Path(row['root']).is_absolute()
            or row['root'] != str(Path(root).resolve())
            or not isinstance(row['repos'], list) or not row['repos']
            or not all(isinstance(repo, str) and re.fullmatch(r'intigraph/[A-Za-z0-9_.-]+', repo)
                       and repo.split('/')[1] not in ('.', '..') for repo in row['repos'])
            or not isinstance(row['jobs'], list) or not row['jobs']
            or not all(job in ('review', 'merge') for job in row['jobs'])):
        raise IdentityError('recruiter has no valid protected UID/root/repository/job scope')
    return Scope(principal, uid, row['root'], tuple(row['repos']), tuple(row['jobs']))


def load(*, root):
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
    return _scope(data, principal=principal, uid=os.geteuid(), root=root)
