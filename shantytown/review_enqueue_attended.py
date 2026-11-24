"""Attended controller Action using the ordinary native classify/enqueue path.

Explicit UID/private-state configuration admits this path. It neither adopts
nor falls back from the separate protected controller/source policies.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

from . import config, review_enqueue as custody
from . import review_enqueue_native as native_adapter
from .review_enqueue_bindings import _claim, _repository
from .actor_identity import IdentityError
from .recruit_store import _directory


def _native(path):
    """Normal native entrypoint, with immutable/owned ancestry, never job code."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise IdentityError('attended native entrypoint must be absolute')
    for p in [*reversed(path.parents), path]:
        meta = p.lstat()
        if (stat.S_ISLNK(meta.st_mode) or meta.st_uid not in (0, os.geteuid())
                or meta.st_mode & 0o022
                or p != path and not stat.S_ISDIR(meta.st_mode)):
            raise IdentityError('attended native entrypoint has unsafe custody')
    if not stat.S_ISREG(path.stat().st_mode):
        raise IdentityError('attended native entrypoint is not regular data')
    return path


def checked_attempt(request, root):
    if (not isinstance(request, dict)
            or set(request) != {'schema', 'intent', 'attempt', 'candidate'}
            or request['schema'] != 'review-enqueue-action/v1'
            or not isinstance(request['intent'], str) or not custody._HASH.fullmatch(request['intent'])
            or not isinstance(request['attempt'], str) or not custody._HASH.fullmatch(request['attempt'])
            or custody._candidate(request['candidate']) != request['intent']
            or request['candidate'].get('report_path') != 'attended'
            or request['candidate']['authority'] != 'https://github.com'):
        raise IdentityError('attended Action request identity unproved')
    cfg, error = config.load_or_default(Path(root))
    if error or not cfg.ephemeral.review_enqueue_enabled:
        raise IdentityError('attended Action configuration absent, off or unproved')
    base = custody.attended_directory(cfg.ephemeral)
    with custody.Store(root, directory=base / 'intents') as store:
        intent = store.read(request['intent'])
    if (intent is None or intent['state'] != 'attempting'
            or intent['attempt'] != request['attempt'] or intent['candidate'] != request['candidate']):
        raise IdentityError('attended Action has no matching consumed attempt')
    return intent, base


def execute(request, *, root, native, python=None, quipu=None, run=subprocess.run):
    deadline = time.monotonic() + 100
    def bounded(argv, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('attended Action budget exhausted')
        kwargs['timeout'] = min(kwargs.get('timeout', remaining), remaining)
        return run(argv, **kwargs)
    intent, base = checked_attempt(request, root)
    native = _native(native)
    interpreter = Path(python or sys.executable)
    if not interpreter.is_absolute() or '..' in interpreter.parts or not os.access(interpreter, os.X_OK):
        raise IdentityError('attended native interpreter is unavailable')
    candidate = intent['candidate']
    bindings = base / 'bindings'
    directory = _directory(bindings, os.geteuid())
    try:
        checkout = _repository(directory, candidate['repo'])
        for suffix in ('.binding.json', '.record.json'):
            try:
                os.stat(intent['id'] + suffix, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise IdentityError('attended binding exists; reconcile without retry')
        _claim(directory, intent['id'], intent['attempt'])
        author = native_adapter.current_author(candidate, quipu=quipu, run=bounded)
        record_name = intent['id'] + '.record.json'
        argv = [str(interpreter), '-I', '-B', str(native)]
        answer = bounded([*argv, 'classify', '--forge', 'github', '--repo', candidate['repo'],
            '--pr', str(candidate['pr']), '--checkout', checkout, '--author', author,
            '--output', str(bindings / record_name)], capture_output=True, text=True,
            timeout=45, umask=0o077)
        if answer.returncode:
            raise IdentityError('attended native classification unproved')
        record = native_adapter._read(directory, record_name, owner=os.geteuid(),
                                      maximum=native_adapter.MAX_BINDING)
        snapshot = record.get('snapshot', {})
        if (record.get('author') != author or not isinstance(record.get('id'), str)
                or not custody._HASH.fullmatch(record['id'])
                or any(snapshot.get(k) != v for k, v in dict(forge='github', repo=candidate['repo'],
                    number=candidate['pr'], head=candidate['head'], base_ref='main',
                    one_way=False, merge_method='squash').items())
                or type(snapshot.get('one_way')) is not bool):
            raise IdentityError('attended native classification moved or differs')
        if native_adapter.current_author(candidate, quipu=quipu, run=bounded) != author:
            raise IdentityError('attended signed approval/author changed')
        # Ordinary native admission still verifies record integrity, exact head,
        # full green CI, holds and shared lane/controller readiness. Never merge.
        answer = bounded([*argv, 'enqueue', str(bindings / record_name), '--checkout', checkout,
            '--expect-record', record['id'], '--diff-bound', '--execute'],
            capture_output=True, text=True, timeout=120)
        lines = answer.stdout.splitlines()
        if answer.returncode or not lines or not lines[-1].startswith('ENQUEUE VERIFIED '):
            raise IdentityError('attended queue outcome UNKNOWN; reconcile without retry')
        result = json.loads(lines[-1].removeprefix('ENQUEUE VERIFIED '))
        if (result.get('record') != record['id'] or result.get('head') != candidate['head']
                or not isinstance(result.get('entry'), str) or not 0 < len(result['entry']) <= 512):
            raise IdentityError('attended native queue receipt binding unproved')
        return dict(schema=request['schema'], intent=request['intent'], attempt=request['attempt'],
                    state='queued', receipt=result['entry'])
    finally:
        os.close(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'native'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--python', type=Path)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(custody.MAX_BYTES + 1)
        if len(raw) > custody.MAX_BYTES:
            raise IdentityError('attended request exceeds bound')
        result = execute(json.loads(raw, object_pairs_hook=custody._unique), **vars(args))
    except Exception as error:
        print('attended enqueue Action unproved: ' + type(error).__name__, file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
