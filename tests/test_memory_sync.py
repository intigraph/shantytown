"""Durable metadata orchestration, without any installed/native lifecycle hook."""
import copy
import json

import pytest

from shantytown import memory_sync as sync
from shantytown.memory_files import MemoryFile
from shantytown.memory_remote import Unproven
from test_memory_batch import Remote, box, files


class Projected(Remote):
    def __init__(self):
        super().__init__()
        self.projection_reads = 0
        self.projection_error = False
        self.wrong_principal = False

    def projection(self):
        self.projection_reads += 1
        if self.projection_error:
            raise Unproven('synthetic projection unknown')
        if self.head is None:
            result = dict(authenticated_owner=self.owner.crew, export={
                'format': 'quipu.memory-files/v1', 'coverage': 'this_repository_owner_records',
                'snapshot': None, 'files': []})
        else:
            result = copy.deepcopy(self.baseline())
        if self.wrong_principal:
            result['authenticated_owner'] = 'urn:example:beta'
        return result


def step(outbox, remote, capture=files, **kwargs):
    return sync.step(outbox, remote, capture, harness='fixture', account='selected', **kwargs)


def state(outbox):
    return json.loads((outbox.root / 'memory-sync.json').read_bytes())


def test_three_triggers_resume_one_capture_then_confirm_fresh_head(tmp_path):
    outbox, remote = box(tmp_path), Projected()
    captures = []

    def capture():
        captures.append(True)
        return files()

    for count in (1, 2):
        result = step(outbox, remote, capture)
        assert result['status'] == 'pending' and result['remaining'] == 3 - count
        assert state(outbox)['accepted_head'] is None
        assert state(outbox)['active_batch'] is not None
        assert len(captures) == 1 and len(remote.writes) == count
    assert step(outbox, remote, capture)['status'] == 'accepted'
    assert state(outbox)['accepted_head'] == remote.head
    assert state(outbox)['active_batch'] is None
    assert len(captures) == 1 and remote.projection_reads == 2
    stamps = {p.name: p.stat().st_mtime_ns for p in outbox.root.iterdir()}
    assert step(outbox, remote, capture)['status'] == 'unchanged'
    assert stamps == {p.name: p.stat().st_mtime_ns for p in outbox.root.iterdir()}
    assert len(captures) == 2 and len(remote.writes) == 3


def test_new_source_changes_wait_until_frozen_batch_accepted(tmp_path):
    outbox, remote = box(tmp_path), Projected()
    assert step(outbox, remote)['status'] == 'pending'
    changed = (MemoryFile('MEMORY.md', b'new native edit'), *files()[1:])
    # An active batch does not call capture, even when the caller's source changed.
    dont_capture = lambda: pytest.fail('recaptured before pending batch completed')
    assert step(outbox, remote, dont_capture)['status'] == 'pending'
    assert step(outbox, remote, dont_capture)['status'] == 'accepted'
    assert step(outbox, remote, lambda: changed)['status'] == 'accepted'
    assert remote.writes[-1]['text'] == 'new native edit'
    assert len(remote.writes) == 4


def test_final_projection_unknown_keeps_exact_active_batch_then_no_recommit(tmp_path):
    outbox, remote = box(tmp_path), Projected()
    step(outbox, remote)
    step(outbox, remote)
    pending = state(outbox)['active_batch']
    remote.projection_error = True
    with pytest.raises(Unproven):
        step(outbox, remote)
    assert len(remote.writes) == 3 and state(outbox)['active_batch'] == pending
    assert state(outbox)['accepted_head'] is None
    remote.projection_error = False
    assert step(outbox, remote)['status'] == 'accepted'
    assert len(remote.writes) == 3 and state(outbox)['active_batch'] is None


def test_lost_reply_resumes_before_source_read_without_new_batch(tmp_path):
    outbox, remote = box(tmp_path), Projected()
    remote.lose_number = 1
    with pytest.raises(Unproven):
        step(outbox, remote)
    pending = state(outbox)['active_batch']
    assert len(remote.writes) == 1
    result = step(outbox, remote, lambda: pytest.fail('unexpected recapture'))
    assert result['remaining'] == 2 and len(remote.writes) == 1
    assert state(outbox)['active_batch'] == pending


def test_unrelated_remote_head_is_not_adopted_before_capture(tmp_path):
    outbox, remote = box(tmp_path), Projected()
    step(outbox, remote, max_new=3)
    accepted = state(outbox)['accepted_head']
    remote.head = 'urn:quipu:memory:snapshot:' + 'f' * 64
    with pytest.raises(Unproven):
        step(outbox, remote, lambda: pytest.fail('unexpected capture'))
    assert state(outbox)['accepted_head'] == accepted and len(remote.writes) == 3


def test_cooperating_trigger_lock_refuses_without_network_or_capture(tmp_path):
    outbox, remote = box(tmp_path), Projected()
    with sync._locked(outbox):
        with pytest.raises(Unproven, match='already active'):
            step(outbox, remote, lambda: pytest.fail('unexpected capture'))
    assert remote.projection_reads == 0 and remote.writes == []


@pytest.mark.parametrize('corruption', ['invalid-json', 'owner', 'batch', 'head', 'symlink'])
def test_invalid_journal_preserved_and_refused_without_network(tmp_path, corruption):
    outbox, remote = box(tmp_path), Projected()
    step(outbox, remote, max_new=0)
    path = outbox.root / 'memory-sync.json'
    value = state(outbox)
    if corruption == 'invalid-json':
        path.write_bytes(b'{')
    elif corruption == 'symlink':
        path.unlink()
        path.symlink_to(tmp_path / 'outside')
    else:
        key = {'owner': 'owner', 'batch': 'active_batch', 'head': 'accepted_head'}[corruption]
        value[key] = 'invalid'
        path.write_text(json.dumps(value))
    before = remote.projection_reads
    with pytest.raises((Unproven, OSError)):
        step(outbox, remote)
    assert remote.projection_reads == before and remote.writes == []
    assert path.is_symlink() if corruption == 'symlink' else path.exists()


def test_wrong_principal_refuses_before_capture_or_journal_creation(tmp_path):
    outbox, remote = box(tmp_path), Projected()
    remote.wrong_principal = True
    with pytest.raises(Unproven):
        step(outbox, remote, lambda: pytest.fail('unexpected capture'))
    assert not (outbox.root / 'memory-sync.json').exists() and remote.writes == []


def test_changed_final_remote_head_preserves_active_batch(tmp_path):
    outbox, remote = box(tmp_path), Projected()
    step(outbox, remote)
    step(outbox, remote)
    original = remote.projection

    def unrelated():
        result = original()
        result['export']['snapshot']['revision'] = 'urn:quipu:memory:snapshot:' + 'e' * 64
        return result

    remote.projection = unrelated
    with pytest.raises(Unproven, match='final memory head differs'):
        step(outbox, remote)
    assert state(outbox)['accepted_head'] is None
    assert state(outbox)['active_batch'] is not None and len(remote.writes) == 3


def test_uncertain_journal_replace_resumes_durable_batch_before_recapture(tmp_path, monkeypatch):
    outbox, remote = box(tmp_path), Projected()
    original = sync.os.replace

    def replaced_then_unknown(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError('synthetic unknown after atomic replace')

    with monkeypatch.context() as patch:
        patch.setattr(sync.os, 'replace', replaced_then_unknown)
        with pytest.raises(OSError):
            step(outbox, remote)
    pending = state(outbox)['active_batch']
    assert pending and remote.writes == []
    assert step(outbox, remote, lambda: pytest.fail('recapture after journal uncertainty'))['remaining'] == 2
    assert state(outbox)['active_batch'] == pending and len(remote.writes) == 1


def test_missing_source_does_not_create_tombstone_or_advance_journal(tmp_path):
    outbox, remote = box(tmp_path), Projected()
    step(outbox, remote, max_new=3)
    before = (outbox.root / 'memory-sync.json').read_bytes()
    with pytest.raises(Unproven, match='explicit deletion'):
        step(outbox, remote, lambda: files()[:-1])
    assert (outbox.root / 'memory-sync.json').read_bytes() == before
    assert len(remote.writes) == 3
