"""Bounded local job identities; never execute a job or infer shell actors."""
from pathlib import Path
import hashlib

from .duties import MAX_BYTES, MAX_ROWS, _name


def job_bindings(root, host):
    """Inventory literal bindings from the same files the job runner reads.

    Shell programs and environment files are separate external inventory:
    parsing their command text cannot prove their effective identity.
    """
    from . import jobs
    directory = jobs.jobs_dir(root)
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise ValueError('unsafe job duty directory')
    paths = sorted(directory.glob('*.toml')) if directory.exists() else []
    if len(paths) > MAX_ROWS:
        raise ValueError('job duty inventory exceeds bound')
    hashes = {}
    for path in paths:
        if path.is_symlink() or path.stat().st_size > MAX_BYTES:
            raise ValueError('unsafe job duty source')
        raw = path.read_bytes()
        if len(raw) > MAX_BYTES:
            raise ValueError('oversized job duty source')
        hashes[path] = hashlib.sha256(raw).digest()
    configured, errors = jobs.load(root)
    if errors:
        raise ValueError('job duty source incomplete')
    if sorted(directory.glob('*.toml')) != paths:
        raise ValueError('job duty population changed')
    for path, digest in hashes.items():
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).digest() != digest:
            raise ValueError('job duty source changed')
    result = []
    for job in configured:
        if not job.enabled or not jobs.runs_here(job, host)[0]:
            continue
        action = job.action
        holder = None
        if action.kind in {'dispatch', 'inbox'}:
            # Role dispatch is resolved live by its existing consumer.
            if not action.to.startswith('role:'):
                holder = _name(action.to)
        elif action.kind == 'exec':
            # Only a direct env argv assignment is a declared actor. A
            # shell, runtime.env or systemd unit requires its own source row.
            argv = list(action.command)
            if argv and Path(argv[0]).name == 'env':
                actors = [word.split('=', 1)[1] for word in argv[1:]
                          if word.startswith('SHANTY_AGENT=')]
                if len(actors) > 1:
                    raise ValueError('ambiguous job duty identity')
                if actors:
                    holder = _name(actors[0])
        if holder is None:
            continue
        digest = hashlib.sha256(job.name.encode()).hexdigest()[:24]
        result.append(dict(id='job:' + digest, holder=holder, kind='scheduled-job',
                           binding='external', priority=action.priority if action.priority is not None else 2,
                           source='jobs:' + job.name, candidates=[], authors=[]))
    return result


def refresh(root, host):
    """Replace only this producer's complete population under the duty lock."""
    from copy import deepcopy
    from .duties import Duties, validate
    from .files import write_json_atomic
    rows = job_bindings(root, host)  # Failure keeps the previous inventory.
    duties = Duties(root)
    with duties.locked():
        before = duties.load()
        after = deepcopy(before)
        # Producer provenance, rather than an ID prefix, controls retirement.
        retained = [r for r in before['entries'] if r.get('producer') != 'local-jobs']
        for row in rows:
            row['producer'] = 'local-jobs'
        after['entries'] = sorted(retained + rows, key=lambda r: r['id'])
        validate(after)
        if sorted(before['entries'], key=lambda r: r['id']) != after['entries']:
            after['revision'] += 1
            if duties.load() != before:
                raise ValueError('job duty inventory changed')
            write_json_atomic(duties.path, after)
            if duties.load() != after:
                raise ValueError('job duty inventory read-back UNKNOWN')
