"""Immutable intent/replay and corruption controls, with no network or native root."""
import hashlib
import json
import os

import pytest

from shantytown.memory_outbox import Outbox
from shantytown.memory_remote import Client, Owner, Unproven, canonical_intent
from shantytown.memory_files import UnsafeMemory

OWNER = Owner('urn:example:deployment', 'urn:example:project', 'urn:example:alpha')


def request():
    return dict(owner=OWNER.wire(), path='MEMORY.md', text='\ufeffλ\r\n',
                expected_snapshot=None, expected_file=None, idempotency_key='one',
                harness='fixture', account='selected')


class Remote(Client):
    def __init__(self):
        super().__init__('https://example.test', OWNER)
        self.accepted = None
        self.reads = self.writes = 0
        self.lose_response = False

    def receipt(self, intent):
        self.reads += 1
        return self.accepted

    def commit(self, intent):
        self.writes += 1
        digest = hashlib.sha256(json.dumps(canonical_intent(intent, OWNER), ensure_ascii=False,
                                           separators=(',', ':')).encode()).hexdigest()
        data = (intent['text'] or '').encode()
        self.accepted = dict(owner=OWNER.wire(), path=intent['path'], request_hash=digest,
                             snapshot='urn:quipu:memory:snapshot:' + digest,
                             committed_at='2026-01-01T00:00:00Z',
                             file=dict(revision='urn:quipu:memory:revision:' + digest,
                                       sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
                                       tombstone=intent['text'] is None))
        if self.lose_response:
            raise Unproven('synthetic lost response')
        return self.accepted


def box(tmp_path):
    root = tmp_path / 'outbox'
    root.mkdir(mode=0o700)
    return Outbox(root, OWNER)


def test_durable_intent_then_receipt_then_unchanged_local_noop(tmp_path):
    outbox, client = box(tmp_path), Remote()
    name = outbox.enqueue(request())
    original = (outbox.root / name).read_bytes()
    assert outbox.enqueue(request()) == name
    accepted = outbox.deliver(name, client)
    stamps = {p.name: p.stat().st_mtime_ns for p in outbox.root.iterdir()}
    assert outbox.deliver(name, client) == accepted
    assert (client.reads, client.writes) == (1, 1)
    assert stamps == {p.name: p.stat().st_mtime_ns for p in outbox.root.iterdir()}
    assert (outbox.root / name).read_bytes() == original


def test_lost_reply_reconciles_receipt_without_a_second_commit(tmp_path):
    outbox, client = box(tmp_path), Remote()
    name = outbox.enqueue(request())
    client.lose_response = True
    with pytest.raises(Unproven):
        outbox.deliver(name, client)
    assert len(list(outbox.root.iterdir())) == 1
    accepted = outbox.deliver(name, client)
    assert accepted == client.accepted
    assert (client.reads, client.writes) == (2, 1)


@pytest.mark.parametrize('corruption', ['changed', 'symlink', 'hardlink', 'partial', 'receipt'])
def test_corruption_refuses_and_preserves_records_without_network(tmp_path, corruption):
    outbox, client = box(tmp_path), Remote()
    name = outbox.enqueue(request())
    path = outbox.root / name
    if corruption == 'changed': path.write_text('changed')
    elif corruption == 'partial': path.write_bytes(b'')
    elif corruption == 'symlink':
        path.unlink()
        target = tmp_path / 'target'
        target.write_text('external')
        path.symlink_to(target)
    elif corruption == 'hardlink': os.link(path, tmp_path / 'second-link')
    elif corruption == 'receipt':
        receipt = outbox.root / name.replace('.json', '.receipt.json')
        receipt.write_text('{"receipt":null}')
        receipt.chmod(0o600)
    with pytest.raises((UnsafeMemory, OSError)):
        outbox.deliver(name, client)
    assert path.exists()
    assert (client.reads, client.writes) == (0, 0)


def test_wrong_selected_owner_and_public_directory_refuse(tmp_path):
    outbox, client = box(tmp_path), Remote()
    name = outbox.enqueue(request())
    client.owner = Owner(OWNER.deployment, OWNER.project, 'urn:example:beta')
    with pytest.raises(Unproven): outbox.deliver(name, client)
    outbox.root.chmod(0o755)
    with pytest.raises(UnsafeMemory): outbox.enqueue(request())
    assert (client.reads, client.writes) == (0, 0)
