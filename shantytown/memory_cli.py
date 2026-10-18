"""Explicit file-memory operations; staging never selects a native root."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

from .memory_files import UnsafeMemory, snapshot
from .memory_outbox import Outbox, MAX_WIRE
from .memory_remote import Client, Owner, Unproven, _json
from .memory_sync import step
from .quipu_auth import CredentialRefused


def configure(parser):
    parser.add_argument('agent', help='crew credential selection, not a guessed owner IRI')
    parser.add_argument('memory_action', choices=('inspect', 'capabilities', 'read', 'export', 'query',
                                                'commit', 'deliver', 'stage', 'sync'))
    parser.add_argument('--server', help='explicit Quipu origin')
    parser.add_argument('--deployment', help='canonical deployment IRI')
    parser.add_argument('--project', help='canonical project IRI')
    parser.add_argument('--owner', help='explicit other crew IRI for read only')
    parser.add_argument('--text', help='bounded literal query within the selected owner')
    parser.add_argument('--directory', type=Path, help='explicit source directory for inspect or sync')
    parser.add_argument('--request', type=Path, help='private exact commit intent JSON')
    parser.add_argument('--outbox', type=Path, help='existing private outbox directory')
    parser.add_argument('--intent', help='existing immutable outbox intent name')
    parser.add_argument('--parent', type=Path, help='existing parent for a NEW staged generation')
    parser.add_argument('--harness', help='explicit source harness attribution for sync')
    parser.add_argument('--account', help='explicit source account attribution for sync')
    parser.add_argument('--max-new', type=int, default=1, help='pending sync attempts, 0..128 (default 1)')


def _required(args, *names):
    if any(getattr(args, name, None) is None for name in names):
        raise Unproven('required memory arguments missing: ' + ', '.join(names))


def _request(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.getuid() or before.st_mode & 0o077
                or before.st_size > MAX_WIRE):
            raise Unproven('memory request must be a bounded private regular file')
        data = stream.read(MAX_WIRE + 1)
        after = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if len(data) > MAX_WIRE or any(getattr(before, k) != getattr(after, k) for k in fields):
        raise Unproven('memory request changed or exceeds bound')
    return _json(data)


def execute(args):
    action = args.memory_action
    if action == 'capabilities':
        return {'transport': 'explicit versioned file operations',
                'native_selection': 'NOT IMPLEMENTED', 'lifecycle_sync': 'NOT IMPLEMENTED',
                'claude': 'staging only; existing native memory unchanged',
                'codex': 'existing read-only startup bridge; generated writeback unsupported',
                'opencode': 'native memory convention unproven; no writeback'}
    if action == 'inspect':
        _required(args, 'directory')
        files = snapshot(args.directory)
        return {'coverage': 'explicit_directory_snapshot',
                'files': [{'path': f.path, 'bytes': len(f.data), 'sha256': f.sha256} for f in files],
                'native_selection': 'UNCHANGED'}
    _required(args, 'server', 'deployment', 'project')
    if args.owner and action not in {'read', 'export', 'query'}:
        raise Unproven('other-owner selection is read-only')
    if action in {'read', 'export', 'query'} and args.owner:
        client = Client(args.server, Owner(args.deployment, args.project, args.owner))
    else:
        client = Client.for_agent(args.root, args.agent, args.server,
                                  args.deployment, args.project)
    if action == 'read':
        return {'historical': True, 'owner': client.owner.wire(), 'snapshot': client.read(),
                'coverage': 'this_repository_owner_records'}
    if action == 'export':
        return {'historical': True, 'export': client.export(), 'owner': client.owner.wire()}
    if action == 'query':
        _required(args, 'text')
        return client.query(args.text)
    if action == 'stage':
        _required(args, 'parent')
        return {'generation': str(client.stage_own(args.parent)),
                'native_selection': 'UNCHANGED'}
    _required(args, 'outbox')
    outbox = Outbox(args.outbox, client.owner)
    if action == 'sync':
        _required(args, 'directory', 'harness', 'account')
        return step(outbox, client, lambda: snapshot(args.directory), harness=args.harness,
                    account=args.account, max_new=args.max_new)
    if action == 'commit':
        _required(args, 'request')
        name = outbox.enqueue(_request(args.request))
    else:
        _required(args, 'intent')
        name = args.intent
    receipt = outbox.deliver(name, client)
    return {'intent': name, 'receipt': receipt, 'native_selection': 'UNCHANGED'}


def command(args):
    try:
        result = execute(args)
    except (UnsafeMemory, CredentialRefused, OSError, ValueError):
        # Do not expose source text, private paths, URLs or credential details.
        print('st: memory result UNKNOWN/refused; preserve source and outbox; no retry.',
              file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0
