"""Remote deferral needs exact fields, not the SDK's comment hydration."""
import subprocess

import pytest

from shantytown import seeds_item
from shantytown.dispatch import DeferUnconfirmed, TrackerWriteLost
from shantytown.protocols import WorkItem, blocker_kind
from shantytown.sd import SdTracker
from test_defer_timeout import PartialBr, dispatcher


class NativePartial(PartialBr, SdTracker):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.quipu = 'https://example.org/quipu'
        self.hydrations = 0
        self.field_reads = 0

    def _bd_for(self, item_id, *args):
        if args[0] == 'show':
            self.hydrations += 1
            raise subprocess.TimeoutExpired('SDK comment hydration', 30)
        return super()._bd_for(item_id, *args)

    def fields(self, item_id):
        self.field_reads += 1
        assert item_id == 'item-1'
        row = self.row
        return WorkItem(id=item_id, title=row['title'], status=row['status'],
            priority=row['priority'], notes=row.get('notes'),
            defer_until=row.get('defer_until'), labels=tuple(row['labels']),
            blocker_kind=blocker_kind(row['labels']))


def native(monkeypatch, **kwargs):
    tracker = NativePartial(**kwargs)
    monkeypatch.setattr(seeds_item, 'read_item', lambda t, key: t.fields(key))
    return tracker


def test_native_defer_never_hydrates_sdk_comments_including_notes_merge(tmp_path, monkeypatch):
    t = native(monkeypatch)
    t.row['notes'] = 'preserve this history'
    result = dispatcher(tmp_path, t).defer('item-1', 'external',
        'wait for publication\nresume_when: release:example/project@v1.2.3',
        until='2026-12-01')
    assert not result.noop
    assert t.row['status'] == 'deferred'
    assert 'preserve this history' in t.row['notes']
    assert t.row['labels'] == ['blocked:external']
    assert len(t.writes) == 2
    assert t.field_reads >= 4  # initial, notes preimage, prepared and final reads
    assert t.hydrations == 0


def test_native_unreadable_fields_never_fall_back_or_write(tmp_path, monkeypatch):
    t = native(monkeypatch)
    def fail(*args):
        raise ValueError('incomplete native fields')
    monkeypatch.setattr(seeds_item, 'read_item', fail)
    with pytest.raises(ValueError, match='incomplete native fields'):
        dispatcher(tmp_path, t).defer('item-1', 'external', 'wait', until='2026-12-01')
    assert t.writes == []
    assert t.hydrations == 0


def test_native_timeout_after_commit_preserves_condition_without_retry(tmp_path, monkeypatch):
    t = native(monkeypatch, fail_write=2, after_commit=True)
    with pytest.raises(DeferUnconfirmed, match='No automatic retry'):
        dispatcher(tmp_path, t).defer('item-1', 'external', 'wait', until='2026-12-01')
    assert len(t.writes) == 2
    assert t.row['defer_until'] == '2026-12-01'
    assert t.hydrations == 0


def test_native_missing_prepared_notes_does_not_hide_work(tmp_path, monkeypatch):
    t = native(monkeypatch, drop='--notes')
    with pytest.raises(TrackerWriteLost):
        dispatcher(tmp_path, t).defer('item-1', 'external', 'wait', until='2026-12-01')
    assert len(t.writes) == 1
    assert t.row['status'] == 'open'
    assert t.hydrations == 0
