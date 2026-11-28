"""Explicit publication by a live task job; no forced updates or test bypasses."""
import re
import subprocess
from pathlib import Path

from . import ephemeral as eph
from .forgejo import parse_remote


def _git(*args):
    return subprocess.run(['git', *args], capture_output=True, text=True, timeout=60)


def publish(rec, head, *, gh, git=_git):
    """Publish the tested commit to this existing PR's actual in-repo head ref.

    A lost reply is UNKNOWN and is never retried here. The caller must inspect
    the remote before deciding whether another action is needed.
    """
    if (not rec or rec.get('job') != 'task' or rec.get('state') not in (eph.LIVE, eph.LAUNCHING)
            or rec.get('uid_binding') or not rec.get('repo') or not rec.get('pr')):
        raise eph.Refused('publication requires a live attended task job repairing its own PR')
    if not re.fullmatch(r'[0-9a-f]{40}', head or ''):
        raise eph.Refused('--head must be the full tested commit SHA')
    workspace, name, repo, pr = rec.get('workspace'), rec.get('name'), rec['repo'], rec['pr']
    if not workspace or not name or not Path(workspace).is_dir():
        raise eph.Refused('task publication workspace is unproved')

    def read(*args):
        result = git('-C', workspace, *args)
        if result.returncode:
            raise eph.Refused('task publication Git precondition failed: ' + args[0])
        return result.stdout.strip()

    if read('symbolic-ref', '--quiet', '--short', 'HEAD') != f'wt/{name}':
        raise eph.Refused('publication source must be this task job\'s own branch')
    if read('rev-parse', 'HEAD') != head:
        raise eph.Refused('local HEAD differs from the tested --head')
    # Share the existing source-cleanliness policy, including provisioning's
    # sanctioned tooling-block edits. Kit files must not strand a repair.
    from . import pr_preflight
    try:
        pr_preflight.require_clean_source(workspace)
    except pr_preflight.Refused as exc:
        raise eph.Refused(str(exc)) from None
    origin = parse_remote(read('remote', 'get-url', 'origin'))
    if not origin or origin[0].lower() not in ('github.com', 'www.github.com') or '/'.join(origin[1:]).lower() != repo.lower():
        raise eph.Refused('publication origin does not match this task job\'s GitHub repository')

    def binding(info):
        branch = (info.get('head') or {}).get('ref')
        tip = (info.get('head') or {}).get('sha')
        base = info.get('base') or {}
        if (info.get('number') != pr or info.get('state') != 'open' or info.get('merged')
                or ((info.get('head') or {}).get('repo') or {}).get('full_name') != repo
                or (base.get('repo') or {}).get('full_name') != repo
                or not isinstance(branch, str) or branch == base.get('ref')
                or branch in ('main', 'master') or not eph._SHA.fullmatch(tip or '')):
            raise eph.Refused('actual in-repository PR head branch is unproved; no fork/base publication')
        if git('-C', workspace, 'check-ref-format', '--branch', branch).returncode:
            raise eph.Refused('actual PR head ref is invalid')
        return branch, tip

    push_urls = read('remote', 'get-url', '--push', '--all', 'origin').splitlines()
    push_origin = parse_remote(push_urls[0]) if len(push_urls) == 1 else None
    if (not push_origin or push_origin[0].lower() not in ('github.com', 'www.github.com')
            or '/'.join(push_origin[1:]).lower() != repo.lower()):
        raise eph.Refused('publication push URL is not uniquely bound to this repository')

    info = gh(f'repos/{repo}/pulls/{pr}')
    branch, tip = binding(info)
    # Fetch only the exact observed source, then prove the normal push is FF.
    read('fetch', '--no-tags', 'origin', tip)
    if git('-C', workspace, 'merge-base', '--is-ancestor', tip, head).returncode:
        raise eph.Refused('PR head is not an ancestor of the tested commit; never force publication')
    if binding(gh(f'repos/{repo}/pulls/{pr}')) != (branch, tip):
        raise eph.Refused('PR publication binding moved; inspect and re-test before publishing')
    # No --force, lease, no-verify or alternate push URL. Re-check local HEAD
    # immediately before the write and push the immutable tested commit.
    if read('rev-parse', 'HEAD') != head:
        raise eph.Refused('local HEAD moved before publication')
    try:
        result = git('-C', workspace, 'push', 'origin', f'{head}:refs/heads/{branch}')
    except (OSError, subprocess.SubprocessError):
        raise eph.Refused('publication acknowledgement UNKNOWN; inspect the remote before any retry') from None
    if result.returncode:
        raise eph.Refused('normal publication push refused or unacknowledged; inspect remote and hook result, never bypass')
    try:
        remote = read('ls-remote', '--heads', 'origin', f'refs/heads/{branch}')
    except (eph.Refused, OSError, subprocess.SubprocessError):
        raise eph.Refused('publication read-back UNKNOWN; inspect remote before any retry') from None
    if remote.split() != [head, f'refs/heads/{branch}']:
        raise eph.Refused('publication read-back UNKNOWN; inspect remote, never blindly repeat the push')
    return dict(repo=repo, pr=pr, branch=branch, head=head, verified=True)
