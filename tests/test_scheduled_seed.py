"""Seed-before-assignment, durable uncertainty and scoped native SDK reuse."""
import base64
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess

import pytest

from shantytown.scheduled_seed import NativeSeedPort, SeedLedger, SeedRequest, SeedUnknown

SDK = os.environ.get('SCHEDULE_TEST_SD_BIN')


def request(**changes):
    binding = dict(job='urn:fixture:job', revision='revision1', host='urn:fixture:host',
                   manifest_sha256='a'*64, agent='fixture-agent', workflow='urn:fixture:workflow',
                   scheduled_at=1000, version=1)
    encoded = base64.urlsafe_b64encode(json.dumps(binding, sort_keys=True,
        separators=(',', ':')).encode()).decode().rstrip('=')
    return SeedRequest(job=binding['job'], run_iri='urn:shuttle:run:scheduled-v1-'+encoded,
        scheduled_at=1000, due_at=1600, recipient='fixture-agent', title='synthetic watch',
        body='Run the synthetic watch and close this seed.', **changes)


class Port:
    scope = 'synthetic-store'
    def __init__(self):
        self.seeds = {}
        self.calls = []
        self.lost_create = False
        self.assign_code = 0
    def create(self, fields):
        self.calls.append('create')
        item = 'fixture-seed'
        self.seeds[item] = dict(id=item, title=fields['title'], description=fields['description'],
            workflow_run=fields['workflow_run'], external_ref=fields['external_ref'],
            due_at=fields['due'], status='open', assignee=None)
        if self.lost_create:
            raise RuntimeError('lost after fixture commit')
        return item
    def read(self, item):
        self.calls.append('read')
        return self.seeds[item]
    def assign(self, item, req):
        self.calls.append('assign')
        assert item in self.seeds and self.seeds[item]['external_ref'] == req.firing
        return self.assign_code


def test_one_seed_readback_before_one_assignment_across_restart(tmp_path):
    port, req = Port(), request()
    ledger = SeedLedger(tmp_path/'ledger.db')
    assert ledger.deliver(req, port) == {'seed':'fixture-seed','assignment':'delivered'}
    ledger.close()
    ledger = SeedLedger(tmp_path/'ledger.db')
    assert ledger.deliver(req, port)['assignment'] == 'delivered'
    assert port.calls == ['create','read','assign']
    ledger.close()


def test_committed_create_with_lost_response_never_recreates_or_assigns(tmp_path):
    port, req = Port(), request()
    port.lost_create = True
    ledger = SeedLedger(tmp_path/'ledger.db')
    with pytest.raises(SeedUnknown):
        ledger.deliver(req, port)
    ledger.close()
    ledger = SeedLedger(tmp_path/'ledger.db')
    with pytest.raises(SeedUnknown):
        ledger.deliver(req, port)
    assert port.calls == ['create'] and len(port.seeds) == 1
    # Exact owner-provided ID/readback resumes assignment without another create.
    ledger.reconcile_created(req, 'fixture-seed', port)
    assert ledger.deliver(req, port)['assignment'] == 'delivered'
    assert port.calls == ['create','read','read','assign']
    ledger.close()


@pytest.mark.parametrize('code', [2, None, True, 99])
def test_uncertain_assignment_is_not_repeated(tmp_path, code):
    ledger, port, req = SeedLedger(tmp_path/'ledger.db'), Port(), request()
    port.assign_code = code
    with pytest.raises(SeedUnknown):
        ledger.deliver(req, port)
    with pytest.raises(SeedUnknown):
        ledger.deliver(req, port)
    assert port.calls == ['create','read','assign']
    ledger.close()


def test_refused_assignment_retains_seed_and_does_not_retry(tmp_path):
    ledger, port, req = SeedLedger(tmp_path/'ledger.db'), Port(), request()
    port.assign_code = 1
    assert ledger.deliver(req, port)['assignment'] == 'refused'
    assert ledger.deliver(req, port)['assignment'] == 'refused'
    assert len(port.seeds) == 1 and port.seeds['fixture-seed']['assignee'] is None
    assert port.calls == ['create','read','assign']
    ledger.close()


def test_changed_policy_or_board_cannot_reinterpret_same_slot(tmp_path):
    ledger, port, req = SeedLedger(tmp_path/'ledger.db'), Port(), request()
    ledger.deliver(req, port)
    with pytest.raises(ValueError, match='changed policy/store'):
        ledger.deliver(replace(req, title='changed'), port)
    port.scope = 'another-store'
    with pytest.raises(ValueError, match='changed policy/store'):
        ledger.deliver(req, port)
    assert port.calls == ['create','read','assign']
    ledger.close()


def test_same_job_slot_key_survives_revision_change_but_digest_refuses(tmp_path):
    req = request()
    prefix, encoded = req.run_iri.rsplit('scheduled-v1-',1)
    binding = json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
    binding['revision'] = 'revision2'
    encoded = base64.urlsafe_b64encode(json.dumps(binding,sort_keys=True,
        separators=(',', ':')).encode()).decode().rstrip('=')
    changed = replace(req, run_iri=prefix+'scheduled-v1-'+encoded)
    assert changed.firing == req.firing
    ledger, port = SeedLedger(tmp_path/'ledger.db'), Port()
    ledger.deliver(req, port)
    with pytest.raises(ValueError):
        ledger.deliver(changed, port)
    assert port.calls == ['create','read','assign']
    ledger.close()


@pytest.mark.parametrize('field,value', [('external_ref','wrong'),('workflow_run','wrong'),
    ('assignee','other'),('status','closed'),('due_at',None)])
def test_bad_readback_never_assigns(tmp_path, field, value):
    port, req = Port(), request()
    read = port.read
    def damaged(item):
        return dict(read(item), **{field:value})
    port.read = damaged
    ledger = SeedLedger(tmp_path/'ledger.db')
    with pytest.raises(SeedUnknown):
        ledger.deliver(req, port)
    assert port.calls == ['create','read']
    ledger.close()


@pytest.mark.parametrize('field,value', [('scheduled_at',True),('due_at',999),
    ('job','literal'),('run_iri','urn:not-canonical'),('recipient','-flag')])
def test_invalid_firing_scope_cannot_create(tmp_path, field, value):
    port, req = Port(), replace(request(), **{field:value})
    ledger = SeedLedger(tmp_path/'ledger.db')
    with pytest.raises(ValueError):
        ledger.deliver(req, port)
    assert port.calls == []
    ledger.close()


def test_ledger_refuses_board_database_and_symlink(tmp_path):
    import sqlite3
    board = tmp_path/'board.db'
    conn = sqlite3.connect(board)
    conn.execute('CREATE TABLE fixture_board(id TEXT)')
    conn.close()
    with pytest.raises(ValueError, match='never a board'):
        SeedLedger(board)
    alias = tmp_path/'alias'
    alias.symlink_to(board)
    with pytest.raises(ValueError):
        SeedLedger(alias)


def test_pure_code_success_and_hold_make_no_seed_but_failure_makes_one(tmp_path):
    ledger, port, req = SeedLedger(tmp_path/'ledger.db'), Port(), request()
    for name in ('succeeded','skipped-by-hold'):
        assert ledger.for_code_outcome(req,port,{'outcome':name,'exit_code':0}) is None
    assert port.calls == []
    failed = {'outcome':'failed','exit_code':1}
    assert ledger.for_code_outcome(req,port,failed)['assignment'] == 'delivered'
    ledger.for_code_outcome(req,port,failed)
    assert port.calls == ['create','read','assign']
    with pytest.raises(ValueError):
        ledger.for_code_outcome(req,port,{'outcome':'failed','exit_code':0})
    ledger.close()


def test_concurrent_reconciliation_cannot_be_overwritten_to_assign_twice(tmp_path):
    first, second = SeedLedger(tmp_path/'ledger.db'), SeedLedger(tmp_path/'ledger.db')
    port, req = Port(), request()
    create = port.create
    def reconciled(fields):
        item = create(fields)
        second.reconcile_created(req,item,port)
        assert second.deliver(req,port)['assignment'] == 'delivered'
        return item
    port.create = reconciled
    with pytest.raises(SeedUnknown, match='already reconciled'):
        first.deliver(req,port)
    assert port.calls.count('create') == 1 and port.calls.count('assign') == 1
    assert first.deliver(req,port)['assignment'] == 'delivered'
    first.close()
    second.close()


@pytest.mark.real_store
@pytest.mark.skipif(not SDK, reason='explicit local SDK fixture binary not supplied')
def test_actual_sdk_keyed_creation_and_readback_before_assignment(tmp_path, monkeypatch):
    from shantytown.sd import SdTracker
    # Entire child environment is fixture-local, including automatic signing
    # identity if the SDK needs one. Never borrow real host/board credentials.
    for key in tuple(os.environ):
        monkeypatch.delenv(key)
    home = tmp_path/'home'
    home.mkdir()
    for key, value in {'HOME':str(home),'XDG_CONFIG_HOME':str(home/'.config'),
        'PATH':os.defpath,'USER':'synthetic','SHANTY_SD_BIN':SDK}.items():
        monkeypatch.setenv(key,value)
    subprocess.run([SDK,'init','--prefix','fixture','--json'],cwd=tmp_path,
                   capture_output=True,check=True,timeout=30)
    raw = subprocess.check_output([SDK,'where','--json'],cwd=tmp_path,timeout=30)
    where = json.loads(raw)
    assert Path(where['database_path']).is_relative_to(tmp_path)
    # init writes project configuration; materialize this explicitly authorized
    # scratch board with a positive control before the existing-store guard.
    subprocess.run([SDK,'--store',where['database_path'],'create','fixture store control','--json'],
                   cwd=tmp_path,capture_output=True,check=True,timeout=30)
    tracker = SdTracker(repo=str(tmp_path),store=where['database_path'],prefix='fixture')
    assigned = []
    def normal_go(argv):
        assert argv[0] == 'go'
        seed = port.read(argv[1])
        assert seed['external_ref'] == req.firing and seed['assignee'] is None
        assigned.append(argv)
        return 0  # explicitly synthetic assignment seam, not a live pane
    port = NativeSeedPort(tracker, normal_go)
    ledger, req = SeedLedger(tmp_path/'ledger.db'), request()
    result = ledger.deliver(req, port)
    assert ledger.deliver(req, port) == result and len(assigned) == 1
    # A separate native keyed-create returns the same real seed, not a fake ID.
    assert port.create(req.fields()) == result['seed']
    assert assigned[0] == ['go',result['seed'],req.recipient,'--quipu-node',req.job,
                          '--note','scheduled firing: '+req.firing]
    ledger.close()
