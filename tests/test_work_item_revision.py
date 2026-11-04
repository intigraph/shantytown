"""Caller revisions reach Seeds unchanged; a conflict never becomes a retry."""
import json
from subprocess import CompletedProcess

import pytest

from shantytown import work_item
from shantytown.br import UpdateConflict
from test_work_item_replace_text import Guarded, operation


class RevisionGuarded(Guarded):
    def __init__(self):
        super().__init__()
        self.revision = 2

    def _bd_for(self, item_id, *argv):
        token = next((v.partition('=')[2] for v in argv
                      if v.startswith('--if-revision=')), None)
        if token != str(self.revision):
            self.calls.append(argv)
            return CompletedProcess(argv, 4, json.dumps({'error': {
                'code': 'CONFLICT', 'message': 'reread and rebase',
                'details': {'schema': 'seed-update-conflict/v1',
                            'expected_revision': int(token), 'current_revision': self.revision,
                            'field_differences': [{'field': 'notes', 'current': 'peer evidence'}]}}}), '')
        result = super()._bd_for(item_id, *argv)
        self.revision += 1
        return result


def test_stale_revision_survives_fresh_admission_read_without_retry(tmp_path):
    tracker = RevisionGuarded()
    args = operation(tmp_path, 'my stale edit', if_revision=1, status='in_progress')
    with pytest.raises(UpdateConflict) as failure:
        work_item.command(args, tracker)
    assert failure.value.details['expected_revision'] == 1
    assert failure.value.details['current_revision'] == 2
    assert 'peer evidence' in str(failure.value)
    assert len(tracker.calls) == 1
    assert '--if-revision=1' in tracker.calls[0]
    assert '--json' in tracker.calls[0]
    assert tracker.notes == 'prior evidence\nresume_when: closed:old'
    assert tracker.revision == 2


def test_explicit_rebased_revision_is_passed_once(tmp_path):
    tracker = RevisionGuarded()
    args = operation(tmp_path, 'merged peer evidence and my edit', if_revision=2)
    assert work_item.command(args, tracker)['result'] == 'verified'
    assert len(tracker.calls) == 1 and '--if-revision=2' in tracker.calls[0]
    assert tracker.revision == 3


@pytest.mark.parametrize('token', [-1, True, '2'])
def test_bad_revision_refuses_before_write(tmp_path, token):
    tracker = RevisionGuarded()
    with pytest.raises(ValueError, match='nonnegative integer'):
        work_item.command(operation(tmp_path, if_revision=token), tracker)
    assert tracker.calls == []


def test_other_backend_cannot_silently_drop_guard(tmp_path):
    class Other:
        def get(self, item_id):
            from shantytown.protocols import WorkItem
            return WorkItem(item_id)

        def update(self, *args, **kwargs):
            pytest.fail('unsupported backend must not write')
    with pytest.raises(ValueError, match='Seeds backend'):
        work_item.command(operation(tmp_path, if_revision=1), Other())


@pytest.mark.parametrize('revision,expected', [(7, 7), (None, None), (True, None), ('7', None)])
def test_show_keeps_exact_numeric_revision_without_another_read(revision, expected):
    from shantytown.sd import SdTracker
    tracker = object.__new__(SdTracker)
    calls = []

    def read(item_id, *args):
        calls.append((item_id, args))
        return CompletedProcess(args, 0, json.dumps([{'id': item_id,
            'title': 'fixture', 'status': 'open', 'revision': revision,
            'dependencies': []}]), '')
    tracker._bd_for = read
    assert work_item.command(type('Args', (), {'item': 'known-id', 'item_action': 'show'})(), tracker)['revision'] == expected
    assert len(calls) == 1
