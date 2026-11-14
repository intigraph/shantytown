"""Render an explicit provision-only slot catalog; never allocate native accounts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from .actor_identity import IdentityError
from .job_launch import validate_manifest
from .job_manifest import document, pinned


def render(first_uid, count, controller_uid, kind, retained, output):
    if (type(first_uid) is not int or type(count) is not int or type(controller_uid) is not int
            or kind not in ('review', 'merge', 'triage', 'task')
            or not 10000 <= first_uid <= first_uid+count-1 <= 0xffffff
            or not 1 <= count <= 1024 or not 10000 <= controller_uid <= 0xffffffff
            or first_uid <= controller_uid < first_uid+count or len(retained)+count > 1024):
        raise IdentityError('explicit bounded slot range and separate controller required')
    files, slots, uids, users, keys = {}, {}, set(), set(), set()
    def add(row, raw):
        name, uid = row['principal'], row['uid']
        if (name in slots or uid in uids or row['username'] in users
                or row['controller_uid'] != controller_uid or uid == controller_uid):
            raise IdentityError('repeated slot identity or mixed/job controller')
        if row.get('review') is not None:
            key = row['review']['public_key']
            if key in keys:
                raise IdentityError('review signing key shared between retained slots')
            keys.add(key)
        files[name+'.json'] = raw
        slots[name] = {'uid':uid, 'sha256':hashlib.sha256(raw).hexdigest()}
        uids.add(uid)
        users.add(row['username'])
    for path, digest in retained:
        path = Path(path)
        raw = pinned(path, digest, 65536)
        row = document(raw)
        name = row.get('principal') if isinstance(row, dict) else None
        validate_manifest(row, name, allow_identity=True)
        if path.name != name+'.json':
            raise IdentityError('retained manifest filename differs from its principal')
        add(row, raw)
    for uid in range(first_uid, first_uid+count):
        suffix = format(uid, '06x')
        name = 'eph-'+kind+'-'+suffix
        row = {'version':1, 'principal':name, 'uid':uid, 'gid':uid,
            'controller_uid':controller_uid, 'username':'_stjobs_'+suffix,
            'home':'/var/lib/shantytown/agents/crew-'+name,
            'root':'/var/lib/shantytown/job-stores/'+name}
        validate_manifest(row, name, allow_identity=True)
        add(row, (json.dumps(row, indent=2)+'\n').encode())
    plan = {'version':1, 'uid_min':min(uids), 'uid_max':max(uids), 'slots':slots}
    files['slots.json'] = (json.dumps(plan, indent=2)+'\n').encode()
    output = Path(output)
    output.mkdir(mode=0o700, parents=True)
    for name, raw in files.items():
        fd = os.open(output/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return {'slots':len(slots), 'slots_json_sha256':hashlib.sha256(files['slots.json']).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first-uid', type=int, required=True)
    parser.add_argument('--count', type=int, required=True)
    parser.add_argument('--controller-uid', type=int, required=True)
    parser.add_argument('--kind', choices=('review', 'merge', 'triage', 'task'), required=True)
    parser.add_argument('--retain', type=Path, action='append', default=[])
    parser.add_argument('--retain-sha256', action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if len(args.retain) != len(args.retain_sha256):
            raise IdentityError('each retained slot needs its explicit SHA256')
        print(json.dumps(render(args.first_uid, args.count, args.controller_uid, args.kind,
            list(zip(args.retain, args.retain_sha256)), args.output), sort_keys=True))
        return 0
    except (IdentityError, OSError, ValueError, KeyError) as error:
        print('REFUSED: '+str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
