"""Ordered multi-file CAS, immutable retry identity and no implicit deletion."""
import hashlib
import json

import pytest

from shantytown import memory_batch as batch
from shantytown.memory_files import MemoryFile
from shantytown.memory_outbox import Outbox
from shantytown.memory_remote import Client, Owner, Unproven, canonical_intent

OWNER = Owner('urn:example:deployment', 'urn:example:project', 'urn:example:alpha')


class Remote(Client):
    def __init__(self):
        super().__init__('https://example.test', OWNER)
        self.head = None
        self.files = {}
        self.accepted = {}
        self.writes = []
        self.receipt_reads = 0
        self.lose_number = None

    def receipt(self, request):
        self.receipt_reads += 1
        return self.accepted.get(request['idempotency_key'])

    def commit(self, request):
        if (request['expected_snapshot'] != self.head or request['expected_file'] !=
                self.files.get(request['path'], {}).get('revision')):
            raise Unproven('synthetic actual CAS conflict')
        digest = hashlib.sha256(json.dumps(canonical_intent(request, OWNER),
            ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        data = request['text'].encode()
        file = dict(revision='urn:quipu:memory:revision:' + digest,
                    sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), tombstone=False)
        self.head = 'urn:quipu:memory:snapshot:' + digest
        self.files[request['path']] = file
        receipt = dict(owner=OWNER.wire(), path=request['path'], file=file,
                       request_hash=digest, snapshot=self.head)
        self.accepted[request['idempotency_key']] = receipt
        self.writes.append(request)
        if len(self.writes) == self.lose_number:
            raise Unproven('synthetic response loss after commit')
        return receipt

    def baseline(self):
        return dict(authenticated_owner=OWNER.crew, export={
            'format': 'quipu.memory-files/v1', 'coverage': 'this_repository_owner_records',
            'snapshot': dict(owner=OWNER.wire(), revision=self.head, files=self.files.copy()),
            'files': [dict(owner=OWNER.wire(), path=p, revision=self.files[p]['revision'], text=r['text'])
                      for p, r in {r['path']: r for r in self.writes}.items()]})


def box(tmp_path):
    root = tmp_path / 'outbox'
    root.mkdir(mode=0o700)
    return Outbox(root, OWNER)


def files():
    return tuple(MemoryFile(p, data) for p, data in [
        ('MEMORY.md', b'# Index\r\n'), ('topics/a.md', 'λ\r\n'.encode()),
        ('topics/b.md', b'last\n')])


def plan(source, baseline=None):
    return batch.plan(OWNER, source, baseline, harness='fixture', account='selected')


def test_middle_lost_response_resumes_exact_batch_without_duplicate_or_native_write(tmp_path):
    outbox, remote = box(tmp_path), Remote()
    requests = plan(files())
    name = batch.freeze(outbox, requests)
    assert batch.freeze(outbox, requests) == name
    native = tmp_path / 'native.md'
    native.write_text('new offline edit after frozen capture')
    remote.lose_number = 2
    with pytest.raises(Unproven):
        batch.deliver(outbox, name, remote)
    assert len(remote.writes) == 2
    assert len(list(outbox.root.glob('*.receipt.json'))) == 1
    result = batch.deliver(outbox, name, remote)
    assert result['status'] == 'batch_delivered'
    assert result['native_selection'] == 'UNCHANGED'
    assert len(remote.writes) == 3
    assert remote.writes == list(requests)
    assert native.read_text() == 'new offline edit after frozen capture'
    stamps = {p.name: p.stat().st_mtime_ns for p in outbox.root.iterdir()}
    assert batch.deliver(outbox, name, remote) == result
    assert len(remote.writes) == 3
    assert stamps == {p.name: p.stat().st_mtime_ns for p in outbox.root.iterdir()}


def test_no_change_does_not_churn_and_does_not_claim_remote_currentness(tmp_path):
    outbox, remote = box(tmp_path), Remote()
    batch.deliver(outbox, batch.freeze(outbox, plan(files())), remote)
    no_change = plan(files(), remote.baseline())
    assert no_change == ()
    result = batch.deliver(outbox, batch.freeze(outbox, no_change), remote)
    assert result['status'] == 'no_changes_against_supplied_baseline'
    assert result['remote_currentness'] == 'NOT PROVEN'
    assert len(remote.writes) == 3


def test_missing_file_is_not_a_tombstone_and_stale_remote_is_not_adopted(tmp_path):
    outbox, remote = box(tmp_path), Remote()
    batch.deliver(outbox, batch.freeze(outbox, plan(files())), remote)
    baseline = remote.baseline()
    with pytest.raises(Unproven):
        plan(files()[:-1], baseline)
    changed = (MemoryFile('MEMORY.md', b'new'), *files()[1:])
    pending = batch.freeze(outbox, plan(changed, baseline))
    remote.head = 'urn:example:another-writer'
    with pytest.raises(Unproven):
        batch.deliver(outbox, pending, remote)
    assert len(remote.writes) == 3
    assert (outbox.root / pending).exists()


def test_first_import_expects_absent_head_not_current_remote_overwrite(tmp_path):
    outbox, remote = box(tmp_path), Remote()
    remote.head = 'urn:example:existing-head'
    name = batch.freeze(outbox, plan(files()))
    with pytest.raises(Unproven):
        batch.deliver(outbox, name, remote)
    assert remote.writes == []


def test_wrong_owner_or_corrupt_manifest_refuses_without_network(tmp_path):
    outbox, remote = box(tmp_path), Remote()
    name = batch.freeze(outbox, plan(files()))
    (outbox.root / name).write_bytes(b'{}')
    with pytest.raises(Unproven):
        batch.deliver(outbox, name, remote)
    assert remote.writes == []
    remote.owner = Owner(OWNER.deployment, OWNER.project, 'urn:example:beta')
    with pytest.raises(Unproven):
        batch.deliver(outbox, name, remote)


def test_one_pending_intent_per_trigger_resumes_without_repeating_accepted_work(tmp_path):
    outbox, remote = box(tmp_path), Remote()
    requests = plan(files())
    name = batch.freeze(outbox, requests)
    zero = batch.deliver(outbox, name, remote, max_new=0)
    assert zero['status'] == 'batch_partial' and zero['remaining'] == 3
    assert remote.writes == [] and remote.receipt_reads == 0
    for count in range(1, 4):
        result = batch.deliver(outbox, name, remote, max_new=1)
        assert len(remote.writes) == count
        assert result['remaining'] == 3 - count
        assert result['status'] == ('batch_delivered' if count == 3 else 'batch_partial')
        assert remote.receipt_reads == count
    stamps = {p.name: p.stat().st_mtime_ns for p in outbox.root.iterdir()}
    assert batch.deliver(outbox, name, remote, max_new=0) == result
    assert remote.writes == list(requests)
    assert remote.receipt_reads == 3
    assert stamps == {p.name: p.stat().st_mtime_ns for p in outbox.root.iterdir()}


def test_lost_reply_counts_as_pending_until_next_trigger_reconciles_receipt(tmp_path):
    outbox, remote = box(tmp_path), Remote()
    name = batch.freeze(outbox, plan(files()))
    batch.deliver(outbox, name, remote, max_new=1)
    remote.lose_number = 2
    with pytest.raises(Unproven):
        batch.deliver(outbox, name, remote, max_new=1)
    assert len(remote.writes) == 2
    # The next trigger spends its single pending allowance reconciling the
    # accepted remote commit, rather than also committing the third file.
    result = batch.deliver(outbox, name, remote, max_new=1)
    assert result['remaining'] == 1 and len(remote.writes) == 2
    result = batch.deliver(outbox, name, remote, max_new=1)
    assert result['status'] == 'batch_delivered' and len(remote.writes) == 3


@pytest.mark.parametrize('limit', [-1, 129, True, 1.5, None, '1'])
def test_invalid_delivery_budget_refuses_before_network(tmp_path, limit):
    outbox, remote = box(tmp_path), Remote()
    name = batch.freeze(outbox, plan(files()))
    with pytest.raises(Unproven):
        batch.deliver(outbox, name, remote, max_new=limit)
    assert remote.writes == []
