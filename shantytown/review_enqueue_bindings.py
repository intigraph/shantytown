"""Controller-only automatic native classification, followed by one enqueue.

Explicit process selection is the opt-in, in addition to the existing OFF flag.
No reviewer-supplied checkout, author, classification or native argv is accepted.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from . import review_enqueue_native as adapter
from . import review_enqueue as custody
from .actor_identity import IdentityError
from .recruit_store import _directory

MAX_REPOSITORIES = 64


def _repository(directory, repo):
    policy = adapter._read(directory, 'repositories.json', owner=os.geteuid(), maximum=65536)
    if (set(policy) != {'version', 'repositories'} or type(policy['version']) is not int
            or policy['version'] != 1 or not isinstance(policy['repositories'], dict)
            or not 0 < len(policy['repositories']) <= MAX_REPOSITORIES):
        raise IdentityError('native repository configuration unproved')
    for name, value in policy['repositories'].items():
        if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name)
                or not isinstance(value, dict) or set(value) != {'checkout'}
                or not isinstance(value['checkout'], str) or not Path(value['checkout']).is_absolute()
                or '..' in Path(value['checkout']).parts):
            raise IdentityError('native repository entry unproved')
    if repo not in policy['repositories']:
        raise IdentityError('repository is not enrolled for automatic binding')
    return policy['repositories'][repo]['checkout']


def _claim(directory, intent, attempt):
    # Durable exclusivity precedes classification (which can consume a scoring
    # budget). A crash or failed command leaves evidence, never an auto-retry.
    fd = os.open(intent + '.prepare.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(custody._bytes(dict(version=1, intent=intent, attempt=attempt)))
        stream.flush(); os.fsync(stream.fileno())
    os.fsync(directory)


def execute(request, *, root, bindings, native, quipu=None, run=subprocess.run):
    deadline = time.monotonic() + 100  # Outer Action timeout is 120 seconds.
    def bounded(argv, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('native Action budget exhausted')
        kwargs['timeout'] = min(kwargs.get('timeout', remaining), remaining)
        return run(argv, **kwargs)
    intent = adapter.checked_attempt(request, root)
    candidate = intent['candidate']
    os.close(adapter._operator_file(Path(native)))
    directory = _directory(Path(bindings), os.geteuid())
    try:
        checkout = _repository(directory, candidate['repo'])
        # Do not replace partial, old or operator-prepared binding evidence.
        for suffix in ('.binding.json', '.record.json'):
            try:
                os.stat(intent['id'] + suffix, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise IdentityError('native binding already exists; reconcile without retry')
        _claim(directory, intent['id'], intent['attempt'])
        author = adapter.current_author(candidate, quipu=quipu, run=bounded)
        record_name = intent['id'] + '.record.json'
        answer = bounded([sys.executable, '-I', str(native), 'classify', '--forge', 'github',
            '--repo', candidate['repo'], '--pr', str(candidate['pr']), '--checkout', checkout,
            '--author', author, '--output', str(Path(bindings) / record_name)],
            capture_output=True, text=True, timeout=45, umask=0o077)
        if answer.returncode:
            raise IdentityError('native classification unproved; no automatic retry')
        record = adapter._read(directory, record_name, owner=os.geteuid(), maximum=adapter.MAX_BINDING)
        snap = record.get('snapshot', {})
        if (record.get('author') != author or not isinstance(record.get('id'), str)
                or not custody._HASH.fullmatch(record['id'])
                or any(snap.get(k) != v for k, v in dict(forge='github', repo=candidate['repo'],
                    number=candidate['pr'], head=candidate['head'], base_ref='main', one_way=False,
                    merge_method='squash').items()) or type(snap.get('one_way')) is not bool):
            raise IdentityError('native classification moved or differs from approved candidate')
        name = intent['id'] + '.binding.json'
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW |
                     os.O_CLOEXEC, 0o600, dir_fd=directory)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(custody._bytes(dict(version=1, checkout=checkout, record=record['id'])))
            stream.flush(); os.fsync(stream.fileno())
        os.fsync(directory)
    finally:
        os.close(directory)
    # Re-read current PR and approval after classification. The native helper
    # still performs its own complete admission; no cached preflight grants GO.
    return adapter.execute(request, root=root, bindings=bindings, native=native,
                           quipu=quipu, run=bounded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'bindings', 'native'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(custody.MAX_BYTES + 1)
        if len(raw) > custody.MAX_BYTES:
            raise IdentityError('native request exceeds bound')
        result = execute(json.loads(raw, object_pairs_hook=custody._unique), **vars(args))
    except Exception as error:
        print('automatic binding Action unproved: ' + type(error).__name__, file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
