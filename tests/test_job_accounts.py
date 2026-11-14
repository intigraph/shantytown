"""Account setup uses private doubles only: no native account, sudo or UID change."""
import copy
import json
import os
import plistlib
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from shantytown import job_accounts as accounts, job_launch as jobs
from shantytown.actor_identity import IdentityError


def entries():
    result = []
    for index, uid in enumerate((51001, 60000)):
        name = 'eph-task-'+format(uid, '06x')
        row = dict(version=1, principal=name, uid=uid, gid=uid, controller_uid=51000,
            username='_stjobs_'+format(uid, '06x'), home='/var/lib/shantytown/agents/crew-'+name,
            root='/var/lib/shantytown/job-stores/'+name)
        jobs.validate_manifest(row, name, allow_identity=True)
        result.append((row, str(index+1)*64))
    return result


class Fake:
    def __init__(self):
        self.receipts, self.native, self.partial = {}, set(), set()
        self.events, self.fail, self.lose_completion = [], None, False

    def receipt(self, row):
        return copy.deepcopy(self.receipts.get(row['uid']))

    def pristine(self, row):
        return row['uid'] not in self.native | self.partial

    def verify(self, row):
        if row['uid'] not in self.native or row['uid'] in self.partial:
            raise IdentityError('fixture partial native identity')

    def reserve(self, row, digest):
        assert row['uid'] not in self.receipts
        self.receipts[row['uid']] = dict(principal=row['principal'], uid=row['uid'], sha256=digest, state='prepared')
        self.events.append(('reserved', row['uid']))

    def create(self, row):
        assert len(self.receipts) == 2
        assert row['uid'] not in self.native
        if self.fail == row['uid']:
            raise OSError('fixture native command refused before mutation')
        self.native.add(row['uid'])
        self.events.append(('created', row['uid']))

    def complete(self, row, digest):
        if self.lose_completion:
            raise OSError('fixture completion write lost')
        self.receipts[row['uid']]['state'] = 'complete'
        self.events.append(('complete', row['uid']))


def test_batch_failure_resumes_without_recreating_completed_account():
    plan, ports = entries(), Fake()
    ports.fail = 60000
    with pytest.raises(OSError): accounts.provision(plan, ports)
    assert ports.events[:2] == [('reserved', 51001), ('reserved', 60000)]
    assert ports.receipts[51001]['state'] == 'complete'
    assert ports.receipts[60000]['state'] == 'prepared'
    original = copy.deepcopy(ports.receipts[51001])
    ports.fail = None
    accounts.provision(plan, ports)
    accounts.provision(plan, ports)
    assert [e for e in ports.events if e[0] == 'created'] == [('created', 51001), ('created', 60000)]
    assert ports.receipts[51001] == original


def test_lost_completion_reconciles_full_native_state_without_replaying_commands():
    plan, ports = entries(), Fake()
    ports.lose_completion = True
    with pytest.raises(OSError): accounts.provision(plan, ports)
    assert ports.native == {51001} and ports.receipts[51001]['state'] == 'prepared'
    ports.lose_completion = False
    accounts.provision(plan, ports)
    assert [e for e in ports.events if e[0] == 'created'] == [('created', 51001), ('created', 60000)]


def test_partial_native_identity_remains_unknown_without_replay_or_receipt_change():
    plan, ports = entries(), Fake()
    ports.fail = 60000
    with pytest.raises(OSError): accounts.provision(plan, ports)
    ports.partial.add(60000)
    ports.fail = None
    before = copy.deepcopy(ports.receipts)
    with pytest.raises(IdentityError): accounts.provision(plan, ports)
    assert ports.receipts == before
    assert [e for e in ports.events if e[0] == 'created'] == [('created', 51001)]


@pytest.mark.parametrize('key,value', [('principal','foreign'),('uid',60001),('sha256','a'*64),('state','unknown'),('extra',True)])
def test_changed_reservation_refuses_before_any_further_native_change(key, value):
    plan, ports = entries(), Fake()
    ports.fail = 60000
    with pytest.raises(OSError): accounts.provision(plan, ports)
    ports.receipts[60000][key] = value
    before = copy.deepcopy(ports.events)
    with pytest.raises(IdentityError): accounts.provision(plan, ports)
    assert ports.events == before


def migration_receipt(row, digest):
    event = dict(action='expand-prepared', old_sha256='a'*64, new_sha256=digest,
        reviewed_commit='b'*40, operator='fixture', time='2026-11-13T00:00:00Z', binding=None)
    return dict(principal=row['principal'], uid=row['uid'], sha256='a'*64, state='complete',
        migrations=[event, dict(event, action='expand-complete')])


def test_complete_step1b_migration_receipt_is_verified_without_rewriting():
    plan, ports = entries(), Fake()
    row, digest = plan[0]
    value = migration_receipt(row, digest)
    ports.receipts[row['uid']] = copy.deepcopy(value)
    ports.native.add(row['uid'])
    accounts.provision(plan, ports)
    assert ports.receipts[row['uid']] == value
    assert [e for e in ports.events if e[0] == 'created'] == [('created',60000)]


@pytest.mark.parametrize('fault', ['partial','new-hash','old-hash','authority','state','extra-field'])
def test_incomplete_or_changed_migration_never_adopts_the_current_hash(fault):
    row, digest = entries()[0]
    value = migration_receipt(row, digest)
    if fault == 'partial': value['migrations'].pop()
    elif fault == 'new-hash': value['migrations'][1]['new_sha256'] = 'c'*64
    elif fault == 'old-hash': value['migrations'][0]['old_sha256'] = 'c'*64
    elif fault == 'authority': value['migrations'][1]['reviewed_commit'] = 'c'*40
    elif fault == 'state': value['state'] = 'prepared'
    else: value['migrations'][1]['extra'] = True
    with pytest.raises(IdentityError): accounts.receipt_state(row, digest, value)


def test_completed_rollback_returns_to_original_receipt_hash():
    row, digest = entries()[0]
    value = migration_receipt(row, digest)
    event = dict(value['migrations'][0], action='rollback-prepared')
    value['migrations'].extend([event, dict(event, action='rollback-complete')])
    assert accounts.receipt_state(row, 'a'*64, value)
    with pytest.raises(IdentityError): accounts.receipt_state(row, digest, value)


@pytest.mark.parametrize('uid,platform', [(501,'darwin'), (0,'linux')])
def test_setup_refuses_before_reading_any_host_path(monkeypatch, uid, platform):
    monkeypatch.setattr(accounts.os, 'geteuid', lambda:uid)
    monkeypatch.setattr(accounts.sys, 'platform', platform)
    monkeypatch.setattr(jobs, 'protected', lambda *a,**kw:pytest.fail('host read before admission'))
    with pytest.raises(IdentityError): accounts.setup('a'*64)


@pytest.mark.parametrize('uid,target,expected', [(0,'inventory',0),(0,'foreign',1),(501,'inventory',1)])
def test_fixed_helper_setup_is_root_only_and_never_a_per_slot_sudo_operation(monkeypatch, uid, target, expected):
    monkeypatch.setattr(jobs.os, 'geteuid', lambda:uid)
    monkeypatch.setattr(jobs, 'protected', lambda *a,**kw:None)
    monkeypatch.setattr(jobs, 'load', lambda *a,**kw:pytest.fail('setup tried a job launch'))
    monkeypatch.setenv('SUDO_UID','0')
    calls = []
    monkeypatch.setattr(accounts, 'setup', lambda digest:calls.append(digest))
    assert jobs.main(['resume-accounts', target, 'a'*64]) == expected
    assert calls == (['a'*64] if uid == 0 and target == 'inventory' else [])


def test_native_creation_uses_only_fixed_disabled_account_properties(monkeypatch):
    row, _ = entries()[0]
    native = accounts.Native.__new__(accounts.Native)
    calls, homes = [], []
    monkeypatch.setattr(accounts, 'root_dir', lambda *a:None)
    monkeypatch.setattr(accounts, 'run', lambda argv:(calls.append(argv) or (0,'')))
    def mkdir(path, **kwargs):
        assert str(path) == '/private'+row['home']
        homes.append(('mkdir',kwargs['mode']))
    def chmod(path, mode):
        assert str(path) == '/private'+row['home']
        homes.append(('chmod',mode))
    monkeypatch.setattr(Path, 'mkdir', mkdir)
    monkeypatch.setattr(Path, 'chmod', chmod)
    native.create(row)
    assert homes == [('mkdir',0o700),('chmod',0o700)]
    assert calls[-1] == ['/usr/sbin/chown','51001:51001','/private'+row['home']]
    assert all(c[:3] == ['/usr/bin/dscl','.','-create'] for c in calls[:-1])
    assert any(c[-2:] == ['AuthenticationAuthority',';DisabledUser;'] for c in calls)
    assert any(c[-2:] == ['UserShell','/usr/bin/false'] for c in calls)
    assert any(c[-2:] == ['IsHidden','1'] for c in calls)


@pytest.mark.parametrize('fault', ['none','admin','ambiguous-admin','partial','duplicate-uid','wrong-home-gid','writable-parent'])
def test_native_verify_requires_complete_non_admin_identity_and_private_home(monkeypatch, fault):
    row, _ = entries()[0]
    native = accounts.Native.__new__(accounts.Native)
    monkeypatch.setattr(accounts, 'inventory', lambda *a:dict({row['username']:51001}, **({'foreign':51001} if fault == 'duplicate-uid' else {})))
    fields = dict(UniqueID='51001', PrimaryGroupID='51001', NFSHomeDirectory=row['home'],
        UserShell='/usr/bin/false', IsHidden='1', AuthenticationAuthority=';DisabledUser;')
    if fault == 'partial': fields['IsHidden'] = '0'
    def run(argv):
        if argv[:4] == ['/usr/bin/dscl', '-plist', '.', '-read']:
            assert argv[4] == '/Groups/'+row['username']
            return 0,plistlib.dumps({'dsAttrTypeStandard:RecordName':[row['username']],
                'dsAttrTypeStandard:PrimaryGroupID':['51001']}).decode()
        if argv[0] == '/usr/bin/dscl':
            return 0,'\n'.join(('dsAttrTypeNative:' if k == 'IsHidden' else '')+k+': '+v for k,v in fields.items())
        if fault == 'admin': return 0,'yes fixture is a member of admin'
        return 1,('no admin group found' if fault == 'ambiguous-admin' else 'no '+row['username']+' is NOT a member of admin')
    monkeypatch.setattr(accounts, 'run', run)
    def protected(path, **kwargs):
        assert path == Path(row['home']).parent and kwargs == {'directory':True}
        if fault == 'writable-parent': raise IdentityError('fixture writable parent')
    monkeypatch.setattr(jobs, 'protected', protected)
    def lstat(path):
        assert str(path) == row['home']
        return SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=51001,st_gid=51002 if fault == 'wrong-home-gid' else 51001)
    monkeypatch.setattr(Path, 'lstat', lstat)
    if fault == 'none': native.verify(row)
    else:
        with pytest.raises(IdentityError): native.verify(row)


@pytest.mark.parametrize('used', ['uid','principal'])
def test_consumed_identity_is_never_a_pristine_resume_target(monkeypatch, used):
    row, _ = entries()[0]
    native = accounts.Native.__new__(accounts.Native)
    native.users, native.groups = {}, {}
    native.used_uids = {row['uid']} if used == 'uid' else set()
    native.used_names = {row['principal']} if used == 'principal' else set()
    monkeypatch.setattr(accounts.os.path, 'lexists', lambda *a:False)
    assert not native.pristine(row)


def test_setup_stops_at_an_account_boundary_and_retains_resumable_reservations(monkeypatch):
    plan, ports = entries(), Fake()
    clock = [0]
    monkeypatch.setattr(accounts.time, 'monotonic', lambda:clock[0])
    create = ports.create
    def first_then_expire(row):
        create(row)
        clock[0] = 2
    ports.create = first_then_expire
    with pytest.raises(IdentityError, match='safe time boundary'):
        accounts.provision(plan, ports, deadline=1)
    assert ports.receipts[51001]['state'] == 'complete'
    assert ports.receipts[60000]['state'] == 'prepared'
    ports.create = create
    accounts.provision(plan, ports)
    assert [e for e in ports.events if e[0] == 'created'] == [('created',51001),('created',60000)]
