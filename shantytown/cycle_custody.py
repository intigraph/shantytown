"""Read-only, item-attested custody for one otherwise unpublishable Git ref.

Comment authors come from the configured tracker, never from receipt fields.
This does not publish, delete, clean or restore any work.
"""
from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
import time
from pathlib import Path


ACCEPT = 'cycle-bundle-accepted-v1 '
VERIFIED = 'cycle-bundle-verified-v1 '
FIELDS = {'agent', 'tree', 'ref', 'head', 'bundle', 'sha256', 'reason'}


def receipt_digest(receipt):
    """The exact payload the independent verifier attests on the same item."""
    return hashlib.sha256(json.dumps(receipt, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def accepted_receipts(comments, card, agent, item):
    """Only a current root card can accept an independently attested receipt.

    A verifier must be a registered crew member other than the target agent;
    the accepting root may also verify. An administrator with a lead is not
    the crew root.
    """
    result = []
    for comment in comments:
        text = comment.get('text', '')
        if not isinstance(text, str) or not text.startswith(ACCEPT):
            continue
        author = comment.get('author')
        root = card(author) if isinstance(author, str) else None
        if (root is None or root.role != 'administrator'
                or root.reports_to or author == agent):
            raise ValueError('bundle custody acceptance is not from the crew root')
        try:
            receipt = json.loads(text[len(ACCEPT):])
        except (ValueError, TypeError) as error:
            raise ValueError('malformed bundle custody acceptance') from error
        if (not isinstance(receipt, dict) or set(receipt) != FIELDS
                or any(not isinstance(v, str) or not v.strip() for v in receipt.values())
                or receipt['agent'] != agent
                or receipt['reason'] not in ('archived', 'gated')
                or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', receipt['head'])
                or not re.fullmatch(r'[0-9a-f]{64}', receipt['sha256'])
                or not receipt['ref'].startswith('refs/heads/')
                or not Path(receipt['tree']).is_absolute()
                or not Path(receipt['bundle']).is_absolute()):
            raise ValueError('invalid exact-ref bundle custody receipt')
        expected = VERIFIED + receipt_digest(receipt)
        verified = False
        for row in comments:
            who = row.get('author')
            if (row.get('text') == expected and isinstance(who, str)
                    and who != agent and card(who) is not None):
                verified = True
                break
        if not verified:
            raise ValueError('bundle custody has no independent item verification')
        result.append({**receipt, 'item': item, 'accepted_by': author})
    if not result:
        raise ValueError('item has no root-accepted bundle custody receipt')
    return result


def _git(tree, *args):
    try:
        proc = subprocess.run(['git', '-C', str(tree), *args], capture_output=True,
                              text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('bundle custody Git verification unavailable') from error
    if proc.returncode:
        raise ValueError('bundle custody Git verification refused')
    return proc.stdout.strip()


def _digest(path):
    digest = hashlib.sha256()
    start = time.monotonic()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
            if time.monotonic() - start > 30:
                raise ValueError('bundle digest exceeded its time bound')
    return digest.hexdigest()


def verify_tree(tree, agent, receipts):
    """Recheck exact local ref/HEAD and a self-contained bundle, or refuse.

    No prerequisite commits are allowed: verify in the source repository alone
    could otherwise accept a thin bundle whose missing history lives only there.
    The independently verified payload's SHA binds the complete archived bytes.
    """
    tree = Path(tree).resolve()
    matching = [r for r in receipts if r['agent'] == agent and Path(r['tree']) == tree]
    if not matching:
        return ''
    if len(matching) != 1:
        raise ValueError('ambiguous bundle custody for tree')
    r = matching[0]
    if (_git(tree, 'symbolic-ref', '-q', 'HEAD') != r['ref']
            or _git(tree, 'rev-parse', '--verify', r['ref']) != r['head']
            or _git(tree, 'rev-parse', '--verify', 'HEAD') != r['head']):
        raise ValueError('bundle custody ref or head moved')
    path = Path(r['bundle'])
    try:
        if path.resolve() != path:
            raise ValueError('bundle custody path must not use symlinks')
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > 2 * 1024**3:
            raise ValueError('bundle custody requires a bounded regular file')
        if _digest(path) != r['sha256']:
            raise ValueError('bundle custody SHA256 mismatch')
        with path.open('rb') as stream:
            # Header only, bounded separately from pack size. v2 and v3 bundles
            # use the same prerequisite marker and blank header terminator.
            header = stream.readline(256)
            if header not in (b'# v2 git bundle\n', b'# v3 git bundle\n'):
                raise ValueError('invalid Git bundle header')
            for _ in range(10000):
                line = stream.readline(8192)
                if line == b'\n':
                    break
                if not line or len(line) == 8192 or line.startswith(b'-'):
                    raise ValueError('bundle custody requires full history, no prerequisites')
            else:
                raise ValueError('bundle header exceeds its bound')
        _git(tree, 'bundle', 'verify', str(path))
        listed = _git(tree, 'bundle', 'list-heads', str(path)).splitlines()
        if f"{r['head']} {r['ref']}" not in listed:
            raise ValueError('exact custody ref/head absent from bundle')
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if identity(path.stat()) != identity(before) or _digest(path) != r['sha256']:
            raise ValueError('bundle custody changed during verification')
    except OSError as error:
        raise ValueError('bundle custody file unavailable') from error
    # Hashing and Git verification can take time. The receipt must still name
    # this tree's current branch and commit after all of those reads, including
    # the final digest; the earlier identity check is not a lease on HEAD.
    if (_git(tree, 'symbolic-ref', '-q', 'HEAD') != r['ref']
            or _git(tree, 'rev-parse', '--verify', r['ref']) != r['head']
            or _git(tree, 'rev-parse', '--verify', 'HEAD') != r['head']):
        raise ValueError('bundle custody ref or head moved during verification')
    return f"{tree}: bundle custody on {r['item']} for {r['ref']} at {r['head']} (root {r['accepted_by']}); preserve bundle and source ref"
