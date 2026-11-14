"""Render reviewed per-slot launch fields; never install, launch, or create accounts.

Run with ``python -m shantytown.job_manifest``. Inputs are explicitly hashed
operator artifacts. Frozen requests/argv belong to each slot, never templates
expanded from a controller's runtime environment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .actor_identity import IdentityError
from .job_launch import FIELDS, IDENTITY_FIELDS, validate_manifest
from .ephemeral import Request, Refused, validate


def document(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise IdentityError('duplicate manifest JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def read(path, maximum):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
        raise IdentityError('renderer requires bounded regular input files')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise IdentityError('renderer input grew beyond its bound')
    return raw


def pinned(path, digest, maximum):
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise IdentityError('explicit artifact SHA256 required')
    raw = read(path, maximum)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise IdentityError('reviewed renderer input digest changed')
    return raw


def render(directory, bindings, destination, *, catalog_sha256, bindings_sha256):
    directory, bindings, destination = map(Path, (directory, bindings, destination))
    plan = document(pinned(directory/'slots.json', catalog_sha256, 1048576))
    additions = document(pinned(bindings, bindings_sha256, 1048576))
    if (not isinstance(plan, dict) or set(plan) != {'version', 'uid_min', 'uid_max', 'slots'}
            or type(plan['version']) is not int or plan['version'] != 1
            or type(plan['uid_min']) is not int or type(plan['uid_max']) is not int
            or not 10000 <= plan['uid_min'] <= plan['uid_max']
            or not isinstance(plan['slots'], dict) or not 1 <= len(plan['slots']) <= 1024
            or not isinstance(additions, dict) or not additions or set(additions) - set(plan['slots'])):
        raise IdentityError('explicit bounded catalog and per-slot launch bindings required')
    if {p.stem for p in directory.glob('eph-*.json')} != set(plan['slots']):
        raise IdentityError('renderer manifests differ from reviewed inventory')
    output, slots = {}, {}
    uids, users, controllers, keys, requests = set(), set(), set(), set(), set()
    for name, reservation in plan['slots'].items():
        if (not isinstance(name, str) or not re.fullmatch(r'eph-(review|merge|triage|task)-[0-9a-f]{6}', name)
                or not isinstance(reservation, dict) or set(reservation) != {'uid', 'sha256'}
                or type(reservation['uid']) is not int
                or not plan['uid_min'] <= reservation['uid'] <= plan['uid_max']):
            raise IdentityError('invalid renderer slot reservation')
        raw = pinned(directory/(name+'.json'), reservation['sha256'], 65536)
        row = document(raw)
        validate_manifest(row, name, allow_identity=True)
        if row['uid'] != reservation['uid'] or row['uid'] in uids or row['username'] in users:
            raise IdentityError('renderer identity collision or changed UID')
        uids.add(row['uid'])
        users.add(row['username'])
        controllers.add(row['controller_uid'])
        if name in additions:
            extra = additions[name]
            if set(row) != IDENTITY_FIELDS or not isinstance(extra, dict) or set(extra) != FIELDS - IDENTITY_FIELDS:
                raise IdentityError('add exactly the launch fields to an identity-only slot; never replace a capability')
            row = dict(row, **extra)
            validate_manifest(row, name)
            try:
                validate(Request(**row['request'], harness=row['harness']))
            except (Refused, TypeError, ValueError) as error:
                raise IdentityError('invalid frozen slot request') from error
            raw = (json.dumps(row, indent=2, sort_keys=True)+'\n').encode()
            if len(raw) > 65536:
                raise IdentityError('rendered launch manifest exceeds the helper byte bound')
        if set(row) == FIELDS:
            request = (row['controller_root'], row['harness'], json.dumps(row['request'], sort_keys=True))
            if request in requests:
                raise IdentityError('ambiguous frozen requests would disable slot selection')
            requests.add(request)
        if row.get('review') is not None:
            key = row['review']['public_key']
            if key in keys:
                raise IdentityError('review signing keys cannot be shared between slots')
            keys.add(key)
        output[name+'.json'] = raw
        slots[name] = {'uid': row['uid'], 'sha256': hashlib.sha256(raw).hexdigest()}
    if len(controllers) != 1 or controllers & uids:
        raise IdentityError('renderer needs one separate controller for the host inventory')
    output['slots.json'] = (json.dumps(dict(plan, slots=slots), indent=2, sort_keys=True)+'\n').encode()
    # Preflight every input before the first output. Never overwrite a working
    # inventory, and retain any incomplete new output after an I/O failure.
    destination.mkdir(mode=0o700)
    for name, raw in output.items():
        fd = os.open(destination/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return {'slots': len(slots), 'bound': len(additions),
            'catalog_sha256': hashlib.sha256(output['slots.json']).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--bindings', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--catalog-sha256', required=True)
    parser.add_argument('--bindings-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(render(args.directory, args.bindings, args.output,
            catalog_sha256=args.catalog_sha256, bindings_sha256=args.bindings_sha256), sort_keys=True))
        return 0
    except (IdentityError, OSError, ValueError, KeyError) as error:
        print('REFUSED: '+str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
