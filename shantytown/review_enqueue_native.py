"""Protected process adapter for review-enqueue-action/v1. Never signs or merges.

A controller-prepared native classification is separate from the job's signed
GateApproval. Both must qualify; neither is converted into the other's receipt.
No bindings, policies, flags or native source are installed by this module.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys

from . import config, gate_verdict, job_review, review_enqueue as custody
from .actor_identity import IdentityError
from .recruit_store import _directory

MAX_BINDING = 2 * 1024 * 1024
CONTROLLER_POLICY = Path('/etc/aegis/service-admission-controller.json')


def _read(directory, name, *, owner, maximum):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                 dir_fd=directory)
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(stream.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != owner
                or meta.st_mode & 0o077 or meta.st_nlink != 1 or meta.st_size > maximum):
            raise IdentityError('adapter binding is not private bounded single-link data')
        return json.loads(stream.read(maximum + 1), object_pairs_hook=custody._unique)


def _operator_file(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise IdentityError('operator path invalid')
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                            os.O_CLOEXEC, dir_fd=parent)
            os.close(parent)
            parent = child
            meta = os.fstat(parent)
            if meta.st_uid != 0 or meta.st_mode & 0o022:
                raise IdentityError('operator source ancestry unprotected')
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                     os.O_CLOEXEC, dir_fd=parent)
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022 or meta.st_nlink != 1:
            os.close(fd)
            raise IdentityError('operator source unprotected')
        return fd
    finally:
        os.close(parent)


def controller_ready():
    # Native queue transport otherwise preserves its legacy behavior when this
    # policy is absent. The new adapter must never take that fallback.
    with os.fdopen(_operator_file(CONTROLLER_POLICY), 'rb') as stream:
        if os.fstat(stream.fileno()).st_size > 4096:
            raise IdentityError('controller policy exceeds bound')
        value = json.loads(stream.read(4097), object_pairs_hook=custody._unique)
    if (set(value) != {'version', 'enabled', 'host', 'uid', 'state_dir'}
            or type(value['version']) is not int or value['version'] != 1
            or value['enabled'] is not True or value['host'] != socket.gethostname()
            or type(value['uid']) is not int or value['uid'] != os.geteuid()):
        raise IdentityError('native controller policy absent, off or host/UID mismatch')


def execute(request, *, root, bindings, native, quipu=None, run=subprocess.run):
    if (not isinstance(request, dict)
            or set(request) != {'schema', 'intent', 'attempt', 'candidate'}
            or request['schema'] != 'review-enqueue-action/v1'
            or not isinstance(request['intent'], str) or not custody._HASH.fullmatch(request['intent'])
            or not isinstance(request['attempt'], str) or not custody._HASH.fullmatch(request['attempt'])
            or custody._candidate(request['candidate']) != request['intent']):
        raise IdentityError('native Action request identity unproved')
    cfg, error = config.load_or_default(Path(root))
    if error or not cfg.ephemeral.review_enqueue_enabled:
        raise IdentityError('native Action configuration absent, off or unproved')
    controller_ready()
    with custody.Store(root) as store:
        intent = store.read(request['intent'])
    if (intent is None or intent['state'] != 'attempting'
            or intent['attempt'] != request['attempt'] or intent['candidate'] != request['candidate']):
        raise IdentityError('native Action has no matching consumed controller attempt')
    candidate = intent['candidate']
    if candidate['authority'] != 'https://github.com':
        raise IdentityError('native Action authority unsupported')
    directory = _directory(Path(bindings), os.geteuid())
    try:
        binding = _read(directory, request['intent'] + '.binding.json',
                        owner=os.geteuid(), maximum=4096)
        record_name = request['intent'] + '.record.json'
        record = _read(directory, record_name, owner=os.geteuid(), maximum=MAX_BINDING)
    finally:
        os.close(directory)
    if (set(binding) != {'version', 'checkout', 'record'} or type(binding['version']) is not int or binding['version'] != 1
            or not isinstance(binding['checkout'], str) or not Path(binding['checkout']).is_absolute()
            or binding['record'] != record.get('id')
            or not isinstance(record.get('id'), str) or not custody._HASH.fullmatch(record['id'])
            or not isinstance(record.get('author'), str) or not record['author']
            or record['author'].lower() == candidate['reviewer'].lower()):
        raise IdentityError('controller native binding unproved')
    snap = record.get('snapshot', {})
    if (any(snap.get(k) != v for k, v in dict(forge='github', repo=candidate['repo'],
            number=candidate['pr'], head=candidate['head'], base_ref='main', one_way=False,
            merge_method='squash').items()) or type(snap.get('one_way')) is not bool):
        raise IdentityError('native classification differs from approved candidate')
    native = Path(native)
    os.close(_operator_file(native))
    # Explicit node-ID read binds the signed graph object to the current forge PR.
    observed = run(['gh', 'api', 'repos/' + candidate['repo'] + '/pulls/' + str(candidate['pr'])],
                   capture_output=True, text=True, timeout=30, check=True)
    pr = json.loads(observed.stdout)
    if (pr.get('node_id') != candidate['pr_node'] or pr.get('number') != candidate['pr']
            or pr.get('head', {}).get('sha') != candidate['head'] or pr.get('state') != 'open'
            or pr.get('base', {}).get('repo', {}).get('full_name') != candidate['repo']):
        raise IdentityError('native forge PR/node/head binding unproved')
    signers = gate_verdict.trusted_signers()
    if candidate['signer'] not in signers:
        raise IdentityError('job signer revoked or unpinned')
    verdict = gate_verdict.approval(quipu or job_review.connection(), repo=candidate['repo'],
        pr=candidate['pr'], node_id=candidate['pr_node'], head=candidate['head'],
        graph=candidate['graph'], signers=signers)
    if (verdict.get('approved') is not True or verdict.get('author_agent') != record.get('author')
            or not any(row.get('record') == candidate['record']
                       and row.get('by') == candidate['reviewer'] for row in verdict.get('approvals', []))):
        raise IdentityError('current independent signed APPROVE unproved')
    # ONE execute. The helper independently verifies record integrity, live CI,
    # head, native review requirements, holds and shared controller admission.
    # A refusal/timeout may follow a write; do not parse it as safe to retry.
    answer = run([sys.executable, '-I', str(native), 'enqueue', str(Path(bindings) / record_name),
                  '--checkout', binding['checkout'], '--expect-record', record['id'],
                  '--diff-bound', '--execute'], capture_output=True, text=True, timeout=120)
    lines = answer.stdout.splitlines()
    if answer.returncode or not lines or not lines[-1].startswith('ENQUEUE VERIFIED '):
        raise IdentityError('native queue outcome UNKNOWN; reconcile without retry')
    result = json.loads(lines[-1].removeprefix('ENQUEUE VERIFIED '))
    if (result.get('record') != record['id'] or result.get('head') != candidate['head']
            or not isinstance(result.get('entry'), str) or not 0 < len(result['entry']) <= 512):
        raise IdentityError('native queue receipt binding unproved')
    return dict(schema=request['schema'], intent=request['intent'], attempt=request['attempt'],
                state='queued', receipt=result['entry'])


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
        # Never expose credential-bearing subprocess output or exception text.
        print('native Action unproved: ' + type(error).__name__, file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
