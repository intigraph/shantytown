"""Private native doubles: shared/unknown groups cannot complete reservations."""
import copy
from pathlib import Path
import plistlib
import stat
from types import SimpleNamespace

import pytest

from shantytown import job_accounts as accounts, job_launch as jobs
from shantytown.actor_identity import IdentityError

PREFIX = 'dsAttrTypeStandard:'
GUID = 'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'


def fixture(monkeypatch, fault, state='prepared'):
    uid = 60000
    name = 'eph-task-00ea60'
    user = '_stjobs_00ea60'
    row = dict(version=1, principal=name, uid=uid, gid=uid, controller_uid=51000,
        username=user, home='/var/lib/shantytown/agents/crew-'+name,
        root='/var/lib/shantytown/job-stores/'+name)
    jobs.validate_manifest(row, name, allow_identity=True)
    users = {user:uid, 'foreign':60001}
    primary = {user:uid, 'foreign':uid if fault == 'foreign-primary' else 60001}
    groups = {user:uid}
    if state == 'fresh':
        users.pop(user)
        primary.pop(user)
        groups.clear()
    group = {PREFIX+'RecordName':[user], PREFIX+'PrimaryGroupID':[str(uid)]}
    if fault in ('foreign-member', 'own-member'):
        group[PREFIX+'GroupMembership'] = ['foreign' if fault == 'foreign-member' else user]
    if fault in ('foreign-guid', 'own-guid', 'unknown-guid'):
        group[PREFIX+'GroupMembers'] = [GUID if fault != 'foreign-guid' else 'FFFFFFFF-BBBB-CCCC-DDDD-EEEEEEEEEEEE']
    if fault == 'nested': group[PREFIX+'NestedGroups'] = [GUID]
    if fault == 'wrong-group': group[PREFIX+'RecordName'] = ['foreign']
    if fault == 'malformed-members': group[PREFIX+'GroupMembership'] = 'foreign'
    calls = []
    def inventory(kind, field):
        calls.append((kind,field))
        if kind == '/Users' and field == 'UniqueID': return dict(users)
        if kind == '/Users' and field == 'PrimaryGroupID':
            if fault == 'unknown-primary': raise IdentityError('fixture unknown primary inventory')
            result = dict(primary)
            if fault == 'incomplete-primary': result.pop('foreign')
            return result
        if kind == '/Groups' and field == 'PrimaryGroupID': return dict(groups)
        raise AssertionError((kind,field))
    def run(argv):
        calls.append(tuple(argv))
        if argv[:4] == ['/usr/bin/dscl','-plist','.','-read']:
            if argv[4] == '/Groups/'+user:
                if fault == 'unknown-members': return 1,''
                if fault == 'malformed-plist': return 0,'not a plist'
                if fault == 'malformed-xml': return 0,'<?xml version="1.0"?><plist><dict>'
                return 0,plistlib.dumps(group).decode()
            assert argv[4:] == ['/Users/'+user,'GeneratedUID']
            return 0,plistlib.dumps({PREFIX+'GeneratedUID': [] if fault == 'unknown-guid' else [GUID]}).decode()
        # Old plaintext membership probe is accepted only to reproduce the
        # original false-ready result, never used by the repaired reader.
        if argv[:4] == ['/usr/bin/dscl','.','-read','/Groups/'+user]:
            return 0,'GroupMembership: '+('foreign' if fault == 'foreign-member' else '')
        if argv[0] == '/usr/sbin/dseditgroup': return 1,'no '+user+' is NOT a member of admin'
        assert argv[:4] == ['/usr/bin/dscl','.','-read','/Users/'+user]
        fields = dict(UniqueID=str(uid), PrimaryGroupID=str(uid), NFSHomeDirectory=row['home'],
            UserShell='/usr/bin/false', IsHidden='1', AuthenticationAuthority=';DisabledUser;')
        return 0,'\n'.join(k+': '+v for k,v in fields.items())
    monkeypatch.setattr(accounts, 'inventory', inventory)
    monkeypatch.setattr(accounts, 'run', run)
    monkeypatch.setattr(jobs, 'protected', lambda *a,**k:None)
    original = Path.lstat
    monkeypatch.setattr(Path, 'lstat', lambda p,*a,**k: SimpleNamespace(st_mode=stat.S_IFDIR|0o700,
        st_uid=uid, st_gid=uid) if str(p)==row['home'] else original(p,*a,**k))
    monkeypatch.setattr(accounts.os.path, 'lexists', lambda path:False)
    native = accounts.Native.__new__(accounts.Native)
    native.users, native.groups = users, groups
    native.used_uids, native.used_names = set(), set()
    receipt = None if state == 'fresh' else dict(principal=name,uid=uid,sha256='a'*64,state=state)
    monkeypatch.setattr(native, 'receipt', lambda _:copy.deepcopy(receipt))
    effects = []
    monkeypatch.setattr(native, 'reserve', lambda *a:effects.append('reserve'))
    monkeypatch.setattr(native, 'create', lambda *a:effects.append('create'))
    monkeypatch.setattr(native, 'complete', lambda *a:effects.append('complete'))
    return row,native,effects,calls,receipt


@pytest.mark.parametrize('state', ['prepared','complete'])
@pytest.mark.parametrize('fault', ['foreign-primary','foreign-member','foreign-guid','nested',
    'unknown-primary','incomplete-primary','unknown-members','malformed-plist','malformed-xml',
    'malformed-members','wrong-group','unknown-guid'])
def test_shared_or_unreadable_native_group_never_reports_complete(monkeypatch, state, fault):
    row,native,effects,calls,receipt = fixture(monkeypatch,fault,state)
    before = copy.deepcopy(receipt)
    with pytest.raises(IdentityError): accounts.provision([(row,'a'*64)],native)
    assert effects == []
    assert native.receipt(row) == before


@pytest.mark.parametrize('fault', ['isolated','own-member','own-guid'])
def test_private_group_reconciles_only_with_complete_native_evidence(monkeypatch, fault):
    row,native,effects,calls,_ = fixture(monkeypatch,fault)
    accounts.provision([(row,'a'*64)],native)
    assert effects == ['complete']
    assert ('/Users','PrimaryGroupID') in calls
    assert ('/usr/bin/dscl','-plist','.','-read','/Groups/'+row['username']) in calls


@pytest.mark.parametrize('fault', ['foreign-primary','unknown-primary','incomplete-primary'])
def test_fresh_foreign_or_unknown_primary_gid_refuses_before_reservation(monkeypatch, fault):
    row,native,effects,_,_ = fixture(monkeypatch,fault,'fresh')
    with pytest.raises(IdentityError): accounts.provision([(row,'a'*64)],native)
    assert effects == []
