"""Explicit text replacement reaches the guarded Seeds transport once."""
from argparse import Namespace
from subprocess import CompletedProcess

import pytest

from shantytown import work_item
from shantytown.protocols import WorkItem
from shantytown.sd import SdTracker


class Guarded(SdTracker):
    def __init__(self, notes='prior evidence\nresume_when: closed:old', description='prior description'):
        self.notes, self.description = notes, description
        self.status = 'open'
        self.calls = []
        self.fault = None

    def get(self, item_id):
        return WorkItem(item_id, notes=self.notes, description=self.description, status=self.status)

    def _bd_for(self, item_id, *argv):
        self.calls.append(argv)
        assert argv[:2] == ('update', item_id)
        assert not any(x.startswith('--replace-text') for x in argv)
        for key in ('notes', 'description', 'status'):
            value = next((x[len(key) + 3:] for x in argv if x.startswith('--' + key + '=')), None)
            if value is not None:
                if key != 'status' and getattr(self, key) and value != getattr(self, key) and '--force' not in argv:
                    return CompletedProcess(argv, 1, '', 'non-empty text requires --force')
                if self.fault != 'lost':
                    setattr(self, key, value)
        if self.fault == 'timeout':
            raise TimeoutError('write committed, response unavailable')
        return CompletedProcess(argv, 0, '{}', '')


def operation(tmp_path, text='prior evidence\nhistorical gate cleared', **kwargs):
    body = tmp_path / 'notes.txt'
    body.write_text(text)
    return Namespace(item='known-id', item_action='update', dry_run=False,
                     notes_file=body, replace_text=True, **kwargs)


@pytest.mark.parametrize('text', ['short replacement', '界\n' * 4000])
def test_explicit_replacement_exact_unicode_body_one_write(tmp_path, text):
    tracker = Guarded()
    args = operation(tmp_path, text, status='in_progress')
    assert work_item.command(args, tracker)['result'] == 'verified'
    assert tracker.notes == text and tracker.status == 'in_progress'
    assert len(tracker.calls) == 1 and tracker.calls[0].count('--force') == 1
    assert tracker.description == 'prior description'


def test_default_nonempty_replacement_refuses_before_transport(tmp_path):
    tracker = Guarded()
    args = operation(tmp_path); args.replace_text = False
    with pytest.raises(ValueError, match='requires --replace-text'):
        work_item.command(args, tracker)
    assert tracker.calls == [] and 'resume_when:' in tracker.notes


@pytest.mark.parametrize('existing', ['', None, 'same exact body'])
def test_empty_or_identical_text_does_not_need_force(tmp_path, existing):
    tracker = Guarded(notes=existing)
    args = operation(tmp_path, 'same exact body'); args.replace_text = False
    assert work_item.command(args, tracker)['result'] == 'verified'
    assert tracker.notes == 'same exact body'
    assert '--force' not in tracker.calls[0]


def test_explicit_dry_run_and_status_only_never_force(tmp_path):
    tracker = Guarded()
    args = operation(tmp_path); args.dry_run = True
    assert work_item.command(args, tracker)['result'] == 'planned'
    assert tracker.calls == [] and 'resume_when:' in tracker.notes
    args = Namespace(item='known-id', item_action='update', dry_run=False, status='in_progress')
    work_item.command(args, tracker)
    assert '--force' not in tracker.calls[0]


@pytest.mark.parametrize('fault', ['timeout', 'lost'])
def test_indeterminate_replacement_never_retries(tmp_path, fault):
    tracker = Guarded(); tracker.fault = fault
    with pytest.raises((TimeoutError, RuntimeError)):
        work_item.command(operation(tmp_path), tracker)
    assert len(tracker.calls) == 1


def test_description_explicit_and_notes_untouched(tmp_path):
    tracker = Guarded(); args = operation(tmp_path)
    args.description_file = args.notes_file; args.notes_file = None
    work_item.command(args, tracker)
    assert tracker.description == 'prior evidence\nhistorical gate cleared'
    assert tracker.notes == 'prior evidence\nresume_when: closed:old'


def test_replacement_flag_without_text_is_refused():
    tracker = Guarded()
    args = Namespace(item='known-id', item_action='update', dry_run=False,
                     status='in_progress', replace_text=True)
    with pytest.raises(ValueError, match='requires a notes/description file'):
        work_item.command(args, tracker)
    assert tracker.calls == []
