"""Operator-pinned native checkout custody; no source/pin installation or repair.

The closure includes every versioned file and local Git config. Non-versioned
files refuse, except bytecode caches which native subprocess flags bypass.
Consumers hold a shared lease through execution; the reviewed refresh lane must
hold the same exclusive lease before changing source or its operator pin.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import configparser
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import subprocess
import sys

from .actor_identity import IdentityError

PIN = Path('/etc/shantytown/native-enqueue-source.json')
LOCK = Path('/etc/shantytown/native-source-custody/source.lock')
MAX_FILES = 10000
MAX_BYTES = 1024 * 1024 * 1024
@dataclass(frozen=True)
class Lease:
    fd: int
    proof: dict


PIN_FIELDS = {'version', 'root', 'entrypoint', 'owner', 'revision', 'closure_sha256', 'lock_file'}
GIT = '/usr/bin/git'


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise IdentityError('duplicate source pin field')
        result[key] = value
    return result


def _require(ok, reason):
    if not ok:
        raise IdentityError(reason)


def _git(root, *args):
    # Only local metadata reads. No fetch, user global config or credential
    # helper is used by these builtins; ignore inherited Git redirections.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
               GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0', GIT_NO_REPLACE_OBJECTS='1')
    result = subprocess.run([GIT, '-c', 'safe.directory=' + str(root), '-c', 'core.fsmonitor=false',
        '-c', 'core.hooksPath=/dev/null', '-C', str(root), *args],
        capture_output=True, timeout=15, env=env, check=True)
    return result.stdout


def _meta(meta):
    return (meta.st_dev, meta.st_ino, meta.st_mode, meta.st_uid, meta.st_gid,
            meta.st_nlink, meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns)


def _owner(meta, owner):
    _require(meta.st_uid in (0, owner), 'source has an unknown owner')
    _require(not meta.st_mode & 0o022, 'source is writable outside its pinned owner')


def _root(root, owner):
    _require(root.is_absolute() and '..' not in root.parts, 'source root path invalid')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for name in root.parts[1:]:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                            os.O_CLOEXEC, dir_fd=fd)
            os.close(fd); fd = child
            _owner(os.fstat(fd), owner)
        _require(os.fstat(fd).st_uid == owner, 'source root owner differs from pin')
        return fd
    except BaseException:
        os.close(fd)
        raise


def measure(root, owner, *, entrypoint=None):
    """Read a frozen checkout into a proposal. Never writes an operator pin."""
    root = Path(root)
    _require(type(owner) is int and 0 <= owner < 2**31, 'source owner invalid')
    directory = _root(root, owner)
    rows = []; total = 0; actual = set()
    def cache(fd):
        entries = os.listdir(fd)
        _require(len(entries) <= MAX_FILES, 'bytecode cache bound exhausted')
        for name in entries:
            meta = os.stat(name, dir_fd=fd, follow_symlinks=False)
            _require(stat.S_ISREG(meta.st_mode) and meta.st_nlink == 1
                and meta.st_uid in (0, owner)
                and re.fullmatch(r'.+\.(?:cpython|pypy)-[0-9]+(?:\.opt-[0-9]+)?\.pyc', name),
                'non-cache code or redirect in excluded bytecode directory')

    def visit(fd, prefix=''):
        nonlocal total
        for name in sorted(os.listdir(fd)):
            if name == '__pycache__':
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                try: cache(child)
                finally: os.close(child)
                continue
            if not prefix and name == '.git':
                continue
            path = prefix + name
            meta = os.stat(name, dir_fd=fd, follow_symlinks=False)
            _owner(meta, owner) if not stat.S_ISLNK(meta.st_mode) else _require(
                meta.st_uid in (0, owner), 'source link has an unknown owner')
            if stat.S_ISDIR(meta.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                                os.O_CLOEXEC, dir_fd=fd)
                try: visit(child, path + '/')
                finally: os.close(child)
                continue
            _require(len(rows) < MAX_FILES, 'source closure file bound exhausted')
            if stat.S_ISLNK(meta.st_mode):
                target = os.readlink(name, dir_fd=fd)
                _require(not target.startswith('/'), 'absolute source link refused')
                normalized = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
                _require(not normalized.startswith('../') and normalized != '..'
                         and '.git' not in PurePosixPath(normalized).parts
                         and '__pycache__' not in PurePosixPath(normalized).parts,
                         'source link escapes the verified closure')
                rows.append(dict(path=path, kind='link', target=target, resolved=normalized))
            else:
                _require(stat.S_ISREG(meta.st_mode) and meta.st_nlink == 1,
                         'source is not single-link regular code')
                total += meta.st_size
                _require(total <= MAX_BYTES, 'source closure byte bound exhausted')
                leaf = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                               os.O_CLOEXEC, dir_fd=fd)
                try:
                    before = os.fstat(leaf); _require(_meta(before) == _meta(meta), 'source changed before read')
                    digest = hashlib.sha256()
                    while block := os.read(leaf, 1024 * 1024): digest.update(block)
                    _require(_meta(os.fstat(leaf)) == _meta(before)
                             and _meta(os.stat(name, dir_fd=fd, follow_symlinks=False)) == _meta(before),
                             'source changed during read')
                finally: os.close(leaf)
                rows.append(dict(path=path, kind='file', owner=meta.st_uid,
                    mode=stat.S_IMODE(meta.st_mode), size=meta.st_size, sha256=digest.hexdigest()))
            actual.add(path)
    try:
        revision = _git(root, 'rev-parse', '--verify', 'HEAD').decode().strip()
        _require(re.fullmatch('[0-9a-f]{40}', revision), 'source revision UNKNOWN')
        tracked = set(filter(None, _git(root, 'ls-tree', '-r', '--name-only', '-z', 'HEAD').decode().split('\0')))
        _require(not any('__pycache__' in PurePosixPath(p).parts for p in tracked),
                 'versioned bytecode cache refused')
        visit(directory)
        _require(actual == tracked, 'source closure has missing or non-versioned files')
        kinds = {r['path']: r['kind'] for r in rows}
        if entrypoint is not None:
            _require(kinds.get(entrypoint) == 'file', 'native entrypoint is not regular verified source')
        _require(all(kinds.get(r['resolved']) == 'file' for r in rows if r['kind'] == 'link'),
                 'source link target is not verified regular code')
        gitfd = os.open('.git', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=directory)
        try:
            _owner(os.fstat(gitfd), owner)
            meta = os.stat('config', dir_fd=gitfd, follow_symlinks=False); _owner(meta, owner)
            _require(stat.S_ISREG(meta.st_mode) and meta.st_nlink == 1 and meta.st_size <= 65536,
                     'local Git config custody UNKNOWN')
            fd = os.open('config', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=gitfd)
            with os.fdopen(fd, 'rb') as stream:
                _require(_meta(os.fstat(stream.fileno())) == _meta(meta), 'Git config changed before read')
                raw = stream.read(65537)
                _require(_meta(os.fstat(stream.fileno())) == _meta(meta)
                    and _meta(os.stat('config', dir_fd=gitfd, follow_symlinks=False)) == _meta(meta),
                    'Git config changed during read')
            _require(len(raw) <= 65536, 'local Git config exceeds bound')
            config = configparser.RawConfigParser(strict=False); config.read_string(raw.decode())
            _require(not any(section.lower().startswith('include') for section in config.sections()),
                     'external Git config is outside source closure')
            total += len(raw)
            _require(total <= MAX_BYTES and len(rows) < MAX_FILES, 'source closure bound exhausted')
            rows.append(dict(path='.git/config', kind='file', owner=meta.st_uid,
                mode=stat.S_IMODE(meta.st_mode), size=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        finally: os.close(gitfd)
        _require(_git(root, 'rev-parse', '--verify', 'HEAD').decode().strip() == revision,
                 'source revision changed during measurement')
    finally: os.close(directory)
    return dict(revision=revision, closure_sha256=hashlib.sha256(_raw(sorted(rows, key=lambda r: r['path']))).hexdigest(),
                file_count=len(rows), bytes=total)


def policy(native=None):
    from .review_enqueue_native import _operator_file
    with os.fdopen(_operator_file(PIN), 'rb') as stream:
        raw = stream.read(4097)
    _require(len(raw) <= 4096, 'source pin exceeds bound')
    value = json.loads(raw, object_pairs_hook=_unique)
    _require(type(value) is dict and set(value) == PIN_FIELDS and type(value['version']) is int
        and value['version'] == 1 and type(value['owner']) is int and 0 <= value['owner'] < 2**31
        and isinstance(value['root'], str) and Path(value['root']).is_absolute()
        and '..' not in Path(value['root']).parts and isinstance(value['entrypoint'], str)
        and not PurePosixPath(value['entrypoint']).is_absolute() and value['entrypoint']
        and '..' not in PurePosixPath(value['entrypoint']).parts
        and re.fullmatch('[0-9a-f]{40}', value.get('revision', ''))
        and re.fullmatch('[0-9a-f]{64}', value.get('closure_sha256', ''))
        and isinstance(value['lock_file'], str) and Path(value['lock_file']) == LOCK,
        'operator source pin schema UNKNOWN')
    if native is not None:
        _require(Path(native) == Path(value['root']) / value['entrypoint'], 'native path differs from operator pin')
    return value


@contextmanager
def verified(native):
    from .review_enqueue_native import _operator_file
    pin = policy(native)
    fd = _operator_file(pin['lock_file'])
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        _require(policy(native) == pin, 'operator source pin changed before lease')
        proof = measure(pin['root'], pin['owner'], entrypoint=pin['entrypoint'])
        _require(all(proof[k] == pin[k] for k in ('revision', 'closure_sha256')),
                 'native revision or full-code closure differs from operator pin')
        yield Lease(fd, proof)
    finally: os.close(fd)


@contextmanager
def refreshing():
    """The reviewed refresh lane uses EX before changing source or its pin."""
    from .review_enqueue_native import _operator_file
    try: PIN.lstat()
    except FileNotFoundError:
        yield None  # No adopted pin: preserve the pre-existing refresh lane.
        return
    pin = policy()
    _require(os.geteuid() in (0, pin['owner']), 'caller is not the pinned source owner')
    fd = _operator_file(pin['lock_file'])
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _require(policy() == pin, 'operator source pin changed before refresh')
        yield Lease(fd, pin)
    finally: os.close(fd)


def check_refresh_fd(fd, root):
    from .review_enqueue_native import _operator_file
    pin = policy()
    _require(type(fd) is int and fd >= 3 and Path(root) == Path(pin['root'])
             and os.geteuid() in (0, pin['owner']), 'refresh caller/root/descriptor unproved')
    check = _operator_file(pin['lock_file'])
    try:
        actual, wanted = os.fstat(fd), os.fstat(check)
        _require((actual.st_dev, actual.st_ino) == (wanted.st_dev, wanted.st_ino),
                 'refresh descriptor differs from operator lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _require(policy() == pin, 'source pin changed during refresh handoff')
    finally: os.close(check)
    return pin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    measure_cmd = sub.add_parser('measure')
    measure_cmd.add_argument('--root', type=Path, required=True)
    measure_cmd.add_argument('--owner', type=int, required=True)
    check = sub.add_parser('check-refresh-fd')
    check.add_argument('--fd', type=int, required=True)
    check.add_argument('--root', type=Path, required=True)
    refresh = sub.add_parser('refresh')
    refresh.add_argument('argv', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.command == 'measure':
            print(json.dumps(measure(args.root, args.owner), sort_keys=True))
            return 0
        if args.command == 'check-refresh-fd':
            check_refresh_fd(args.fd, args.root)
            print('SOURCE_REFRESH_EXCLUSIVE_LEASE_VERIFIED')
            return 0
        argv = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
        _require(argv and Path(argv[0]).is_absolute(), 'refresh requires explicit absolute operator command')
        with refreshing() as lease:
            if lease is None:
                return subprocess.run(argv).returncode
            env = dict(os.environ, AEGIS_NATIVE_SOURCE_REFRESH_FD=str(lease.fd))
            return subprocess.run(argv, env=env, pass_fds=(lease.fd,)).returncode
    except BlockingIOError:
        if args.command == 'refresh':
            print('SKIP source refresh: native source lease busy')
            return 0
        print('native source custody UNKNOWN: BlockingIOError', file=sys.stderr)
        return 1
    except Exception as error:
        print('native source custody UNKNOWN: ' + type(error).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
