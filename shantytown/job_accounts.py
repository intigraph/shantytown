"""Root-only macOS setup for exact reserved job identities; no launch or key copy.

Tambo delegates through the installed fixed helper. This module is not an
allocator: the protected catalog and durable receipts name every identity.
"""
from __future__ import annotations

from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
import time
from xml.parsers.expat import ExpatError

from . import job_launch as jobs
from .actor_identity import IdentityError


def receipt_state(spec, digest, value):
    if (not isinstance(value, dict) or set(value) - {'principal', 'uid', 'sha256', 'state', 'migrations'}
            or value.get('principal') != spec['principal'] or type(value.get('uid')) is not int
            or value['uid'] != spec['uid'] or value.get('state') not in ('prepared', 'complete')
            or not isinstance(value.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', value['sha256'])):
        raise IdentityError('retained account reservation differs; never recycle it')
    complete = value['state'] == 'complete'
    effective = value['sha256']
    if 'migrations' in value:
        history = value['migrations']
        if not complete or not isinstance(history, list) or len(history) not in (2, 4):
            raise IdentityError('partial or unknown account migration; retain it')
        fields = {'action', 'old_sha256', 'new_sha256', 'reviewed_commit', 'operator', 'time', 'binding'}
        for index in range(0, len(history), 2):
            before, after = history[index:index+2]
            action = 'expand' if index == 0 else 'rollback'
            for event in (before, after):
                if (not isinstance(event, dict) or set(event) != fields
                        or not all(isinstance(event[k], str) and re.fullmatch('[0-9a-f]{64}', event[k]) for k in ('old_sha256', 'new_sha256'))
                        or not isinstance(event['reviewed_commit'], str) or not re.fullmatch('[0-9a-f]{40}', event['reviewed_commit'])
                        or not isinstance(event['operator'], str) or not event['operator']
                        or not isinstance(event['time'], str) or not event['time']):
                    raise IdentityError('migration evidence is incomplete')
            if (before['action'] != action+'-prepared' or after['action'] != action+'-complete'
                    or any(before[k] != after[k] for k in fields-{'action', 'time'})
                    or before['old_sha256'] != value['sha256']
                    or effective != before['old_sha256' if index == 0 else 'new_sha256']):
                raise IdentityError('migration completion does not match its preparation')
            effective = before['new_sha256' if index == 0 else 'old_sha256']
    if effective != digest:
        raise IdentityError('account receipt does not bind the current manifest')
    return complete


def provision(entries, ports, *, deadline=None):
    """Resume exact reservations; every fresh UID is reserved before creation."""
    def budget():
        if deadline is not None and time.monotonic() >= deadline:
            raise IdentityError('account setup reached a safe time boundary; retain reservations for explicit resume')
    fresh, pending, reconciled = [], [], []
    for spec, digest in entries:
        budget()
        value = ports.receipt(spec)
        if value is None:
            if not ports.pristine(spec):
                raise IdentityError('slot identity/home is occupied; no adoption')
            fresh.append((spec, digest))
        elif receipt_state(spec, digest, value):
            ports.verify(spec)
        elif ports.pristine(spec):
            pending.append((spec, digest))
        else:
            # A lost completion write is reconcilable only with FULL native
            # proof. Partial accounts never cause blind native command replay.
            ports.verify(spec)
            reconciled.append((spec, digest))
    for spec, digest in fresh:
        budget()
        ports.reserve(spec, digest)
    for spec, digest in reconciled:
        budget()
        ports.complete(spec, digest)
    for spec, digest in pending + fresh:
        budget()
        ports.create(spec)
        ports.verify(spec)
        ports.complete(spec, digest)


def regular(path, maximum=65536):
    jobs.protected(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
            raise IdentityError('invalid bounded account input')
        raw = stream.read(maximum+1)
    if len(raw) > maximum:
        raise IdentityError('account input grew beyond its bound')
    return raw


def root_dir(path):
    try:
        path.mkdir(mode=0o755)
    except FileExistsError:
        pass
    jobs.protected(path, directory=True)


def lock(stack, path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    stream = stack.enter_context(os.fdopen(fd, 'r+'))
    info = os.fstat(stream.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_nlink != 1:
        raise IdentityError('invalid protected account lock')
    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)


def run(argv):
    # A descendant retaining a pipe cannot stall readback after its parent exits.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
            env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL':'C'})
        deadline = time.monotonic()+10
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline or out.tell() > 1048576 or err.tell() > 1048576:
                    raise IdentityError('native account command exceeded its budget; retain reservation')
                time.sleep(0.02)
            if out.tell() > 1048576 or err.tell() > 1048576:
                raise IdentityError('native account output exceeded its bound')
            out.seek(0)
            return process.returncode, out.read(1048577).decode()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def inventory(kind, field):
    code, text = run(['/usr/bin/dscl', '.', '-list', kind, field])
    if code or not text.strip():
        raise IdentityError('native account inventory is unknown')
    result = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[0] in result or not re.fullmatch('-?[0-9]+', parts[1]):
            raise IdentityError('native account inventory is malformed')
        number = int(parts[1])
        if not -(2**31) <= number <= 2**32-1:
            raise IdentityError('native account ID exceeds uid_t')
        result[parts[0]] = number & 0xffffffff
    return result


def consumed(directory):
    uids, names = set(), set()
    paths = list(directory.iterdir())
    if len(paths) > 1025:
        raise IdentityError('consumed job identity inventory exceeds its bound')
    for path in paths:
        if path.name == '.lock':
            continue
        value = json.loads(regular(path, 4096))
        if (not isinstance(value, dict) or set(value) != {'uid', 'principal', 'sha256'}
                or type(value['uid']) is not int or not 10000 <= value['uid'] <= 0xffffffff
                or not isinstance(value['principal'], str) or not jobs._NAME.fullmatch(value['principal'])
                or path.name != value['principal']+'.json'
                or not isinstance(value['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', value['sha256'])
                or value['uid'] in uids or value['principal'] in names):
            raise IdentityError('consumed job identity receipt is unknown')
        uids.add(value['uid'])
        names.add(value['principal'])
    return uids, names


class Native:
    def __init__(self, directory):
        self.receipts = directory/'account-receipts'
        root_dir(self.receipts)
        self.users, self.groups = inventory('/Users', 'UniqueID'), inventory('/Groups', 'PrimaryGroupID')
        self.used_uids, self.used_names = consumed(directory/'used')

    def receipt(self, spec):
        path = self.receipts/(str(spec['uid'])+'.json')
        try:
            raw = regular(path)
        except FileNotFoundError:
            return None
        if stat.S_IMODE(path.lstat().st_mode) != 0o600:
            raise IdentityError('account receipt must remain root-private')
        return json.loads(raw)

    def pristine(self, spec):
        if (spec['username'] in self.users or spec['username'] in self.groups
                or spec['uid'] in self.users.values() or spec['gid'] in self.groups.values()
                or spec['uid'] in self.used_uids or spec['principal'] in self.used_names
                or os.path.lexists(spec['home'])):
            return False
        # An otherwise unused GID can already be another user's primary group,
        # even when no group record exists. Unknown inventory cannot reserve it.
        primary = inventory('/Users', 'PrimaryGroupID')
        if set(primary) != set(self.users):
            raise IdentityError('native primary-group inventory is incomplete or changed')
        return spec['gid'] not in primary.values()

    def verify(self, spec):
        users, groups = inventory('/Users', 'UniqueID'), inventory('/Groups', 'PrimaryGroupID')
        primary = inventory('/Users', 'PrimaryGroupID')
        if (set(primary) != set(users) or primary.get(spec['username']) != spec['gid']
                or any(gid == spec['gid'] and name != spec['username'] for name, gid in primary.items())
                or users.get(spec['username']) != spec['uid'] or groups.get(spec['username']) != spec['gid']
                or list(users.values()).count(spec['uid']) != 1 or list(groups.values()).count(spec['gid']) != 1):
            raise IdentityError('native job UID/GID uniqueness is unproved')
        expected = {'UniqueID':str(spec['uid']), 'PrimaryGroupID':str(spec['gid']), 'NFSHomeDirectory':spec['home'],
            'UserShell':'/usr/bin/false', 'IsHidden':'1', 'AuthenticationAuthority':';DisabledUser;'}
        code, text = run(['/usr/bin/dscl', '.', '-read', '/Users/'+spec['username'], *expected])
        fields = {}
        for line in text.splitlines():
            key, separator, value = line.removeprefix('dsAttrTypeNative:').partition(':')
            if not separator or key.strip() in fields:
                raise IdentityError('native account properties are ambiguous')
            fields[key.strip()] = value.strip()
        if code or fields != expected:
            raise IdentityError('job account is only partially provisioned')
        self.verify_group(spec)
        code, text = run(['/usr/sbin/dseditgroup', '-o', 'checkmember', '-m', spec['username'], 'admin'])
        if code == 0 or text.strip() != 'no '+spec['username']+' is NOT a member of admin':
            raise IdentityError('job account non-admin membership is unproved')
        jobs.protected(Path(spec['home']).parent, directory=True)
        info = Path(spec['home']).lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != spec['uid'] or info.st_gid != spec['gid'] or info.st_mode & 0o077:
            raise IdentityError('job home is not private to its identity')

    @staticmethod
    def verify_group(spec):
        # Read the full record as a plist: absent membership attributes in a
        # successful full read mean empty, unlike a failed single-key query.
        prefix = 'dsAttrTypeStandard:'
        def record(path, *fields):
            code, text = run(['/usr/bin/dscl', '-plist', '.', '-read', path, *fields])
            try:
                value = plistlib.loads(text.encode())
            except (ValueError, TypeError, plistlib.InvalidFileException, ExpatError) as error:
                raise IdentityError('native group membership is unreadable') from error
            if code or not isinstance(value, dict) or not value or len(value) > 16384:
                raise IdentityError('native group membership is unknown')
            return value
        def values(record, key):
            value = record.get(prefix+key, [])
            if (not isinstance(value, list) or len(value) > 16384
                    or any(not isinstance(item, str) or not item for item in value)):
                raise IdentityError('native group membership is malformed')
            return value
        group = record('/Groups/'+spec['username'])
        if (values(group, 'RecordName') != [spec['username']]
                or values(group, 'PrimaryGroupID') != [str(spec['gid'])]
                or any(name != spec['username'] for name in values(group, 'GroupMembership'))
                or values(group, 'NestedGroups')):
            raise IdentityError('native job group is shared or its identity is unproved')
        members = values(group, 'GroupMembers')
        if members:
            own = values(record('/Users/'+spec['username'], 'GeneratedUID'), 'GeneratedUID')
            if (len(own) != 1 or not re.fullmatch(
                    r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', own[0])
                    or any(member.casefold() != own[0].casefold() for member in members)):
                raise IdentityError('native group UUID membership is shared or unproved')

    def save(self, spec, digest, state, exclusive):
        path = self.receipts/(str(spec['uid'])+'.json')
        raw = (json.dumps(dict(principal=spec['principal'], uid=spec['uid'], sha256=digest, state=state), sort_keys=True)+'\n').encode()
        if exclusive:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        else:
            current = regular(path)
            if receipt_state(spec, digest, json.loads(current)):
                return
            fd, temporary = tempfile.mkstemp(prefix='.account-', dir=self.receipts)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                if regular(path) != current:
                    raise IdentityError('account reservation changed before completion')
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        parent = os.open(self.receipts, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)

    def reserve(self, spec, digest):
        self.save(spec, digest, 'prepared', True)

    def complete(self, spec, digest):
        self.save(spec, digest, 'complete', False)

    def create(self, spec):
        for path in ('/private/var', '/private/var/lib', '/private/var/lib/shantytown', '/private/var/lib/shantytown/agents'):
            root_dir(Path(path))
        for target, properties in (
            ('/Groups/'+spec['username'], {'PrimaryGroupID':str(spec['gid']), 'Password':'*'}),
            ('/Users/'+spec['username'], {'UniqueID':str(spec['uid']), 'PrimaryGroupID':str(spec['gid']),
             'NFSHomeDirectory':spec['home'], 'UserShell':'/usr/bin/false', 'Password':'*',
             'AuthenticationAuthority':';DisabledUser;', 'IsHidden':'1'})):
            for key, value in properties.items():
                if run(['/usr/bin/dscl', '.', '-create', target, key, value])[0]:
                    raise IdentityError('native account creation failed; retain reservation')
        home = Path('/private'+spec['home'])
        home.mkdir(mode=0o700)
        home.chmod(0o700)
        if run(['/usr/sbin/chown', str(spec['uid'])+':'+str(spec['gid']), str(home)])[0]:
            raise IdentityError('job home ownership is unproved')


def setup(expected_sha256):
    if os.geteuid() != 0 or sys.platform != 'darwin':
        raise IdentityError('account setup requires separately admitted root execution on macOS')
    if not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise IdentityError('exact protected catalog digest required')
    directory = jobs.BASE
    jobs.protected(directory, directory=True)
    with ExitStack() as stack:
        lock(stack, directory/'.account-lock')
        root_dir(directory/'used')
        lock(stack, directory/'used/.lock')
        raw = regular(directory/'slots.json', 1048576)
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise IdentityError('protected account catalog changed')
        entries = jobs.inventory()
        if regular(directory/'slots.json', 1048576) != raw:
            raise IdentityError('account catalog changed during verification')
        # Leave margin inside the cross-repo caller's 30-minute process budget
        # for one bounded native account sequence to finish before stopping.
        provision(entries, Native(directory), deadline=time.monotonic()+27*60)
    return len(entries)
