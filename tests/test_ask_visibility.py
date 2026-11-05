"""No ASK can be hidden by structured, generic, or producer deferrals."""
from argparse import Namespace
import subprocess
from unittest.mock import Mock

import pytest

from shantytown.ask_visibility import ASK_LABELS, is_ask, refuse_deferral
from shantytown.dispatch import DeferRefused, Dispatcher
from shantytown.files import FilesTracker, FilesRegistry
from shantytown.protocols import WorkItem
from shantytown.tmux import NullPanes
from shantytown import producer_capacity, work_item

CASES = [("Technical control", [label]) for label in sorted(ASK_LABELS)] + [("ASK Stiwi no colon needed", [])]


@pytest.mark.parametrize('title,labels', CASES)
@pytest.mark.parametrize('dry_run', [False, True])
def test_structured_and_generic_refuse_before_any_write(tmp_path, title, labels, dry_run):
    tracker = FilesTracker(tmp_path / 'items')
    tracker.update('lab-1', title=title, labels=labels, status='open')
    before = tracker._path('lab-1').read_bytes()
    d = Dispatcher(FilesRegistry(tmp_path / 'crew'), tracker, NullPanes())
    with pytest.raises(DeferRefused, match='bsf8.*Brief.*Later'):
        d.defer('lab-1', 'external', 'private control', until='2027-01-01', dry_run=dry_run)
    assert tracker._path('lab-1').read_bytes() == before
    args = Namespace(item='lab-1', item_action='update', status='deferred', dry_run=dry_run)
    with pytest.raises(ValueError, match='bsf8.*Brief.*Later'):
        work_item.command(args, tracker)
    assert tracker._path('lab-1').read_bytes() == before


@pytest.mark.parametrize('title,labels', CASES)
@pytest.mark.parametrize('change', [{'status':'deferred'}, {'defer_until':'2027-01-01'}])
def test_pending_classification_cannot_be_removed_in_same_deferral(title, labels, change):
    before = WorkItem('lab-1', title=title, labels=labels)
    with pytest.raises(ValueError, match='Brief.*Later'):
        refuse_deferral(before, change | {'labels': [], 'title': 'technical disguise'})


def test_new_human_label_and_ask_title_are_guarded_but_clear_and_technical_defer_work():
    ordinary = WorkItem('lab-1', title='Technical control', labels=['security'])
    refuse_deferral(ordinary, {'status':'deferred'})
    for fields in [{'blocker_kind':'blocked:human'}, {'labels':['desk']}, {'title':'ASK Stiwi: pick'}]:
        with pytest.raises(ValueError):
            refuse_deferral(ordinary, {'status':'deferred'} | fields)
    ask = WorkItem('lab-2', title='ASK Stiwi: pick')
    refuse_deferral(ask, {'status':'open', 'defer_until':''})
    assert not is_ask(WorkItem('lab-3', title='Discuss ASK Stiwi syntax', labels=['desk-notes']))


def test_structured_human_blocker_uses_the_same_ask_and_no_deferral_rule():
    item = WorkItem('lab-1', title='Choose an option', blocker_kind='blocked:human')
    assert is_ask(item)
    with pytest.raises(ValueError, match='bsf8'):
        refuse_deferral(item, {'status': 'deferred', 'blocker_kind': None})
    assert not is_ask(WorkItem('lab-2', title='Wait for service', blocker_kind='blocked:external'))


@pytest.mark.parametrize('labels', ['technical, needs-stiwi ', [{'name': ' desk '}]])
def test_wire_label_forms_share_the_no_deferral_classification(labels):
    item = {'title': 'Choose an option', 'labels': labels}
    assert is_ask(item)
    with pytest.raises(ValueError, match='bsf8'):
        refuse_deferral(item, {'status': 'deferred', 'labels': []})


@pytest.mark.parametrize('title,labels', CASES)
def test_unassigned_sdk_producer_refuses_before_execute(title, labels):
    tracker = Mock()
    tracker.get.return_value = WorkItem('lab-1', title=title, labels=labels)
    execute = Mock(return_value=subprocess.CompletedProcess([], 0))
    with pytest.raises(ValueError, match='Brief.*Later'):
        producer_capacity.run(['update','lab-1','--status','deferred'], tracker, execute, Mock())
    execute.assert_not_called()


@pytest.mark.parametrize('prefix', [' ', '\t\n', '\u2003'])
@pytest.mark.parametrize('operation', ['create', 'update'])
def test_sdk_normalized_ask_title_refuses_before_execution(prefix, operation):
    tracker = Mock()
    tracker.get.return_value = WorkItem('lab-1', title='Technical control')
    title = prefix + 'ASK Stiwi: choose' + ' \t'
    arguments = (['create', title] if operation == 'create'
                 else ['update', 'lab-1', '--title', title])
    execute = Mock(return_value=subprocess.CompletedProcess([], 0))
    with pytest.raises(ValueError, match='Brief.*Later'):
        producer_capacity.run(arguments + ['--defer', '2027-01-01'],
                              tracker, execute, Mock())
    execute.assert_not_called()


@pytest.mark.parametrize('operation', ['create', 'update'])
def test_normalized_technical_title_still_allows_future_date(operation):
    tracker = Mock()
    tracker.get.return_value = WorkItem('lab-1', title='Technical control')
    title = ' \tDiscuss ASK Stiwi syntax '
    arguments = (['create', title] if operation == 'create'
                 else ['update', 'lab-1', '--title', title])
    arguments += ['--defer', '2027-01-01']
    execute = Mock(return_value=subprocess.CompletedProcess([], 0))
    producer_capacity.run(arguments, tracker, execute, Mock())
    execute.assert_called_once_with(arguments)


def test_normalized_existing_ask_cannot_be_disguised_during_deferral():
    before = WorkItem('lab-1', title=' \tASK Stiwi: choose')
    with pytest.raises(ValueError, match='Brief.*Later'):
        refuse_deferral(before, {'title': 'Technical disguise', 'defer_until': '2027-01-01'})

@pytest.mark.parametrize('change', [{'labels': ['decision-stiwi']}, {'labels': ['desk']}, {'title': 'ASK Stiwi: choose'}])
def test_existing_deferred_cannot_gain_ask_class_without_reopening(change):
    before = WorkItem('lab-1', title='Technical control', status='deferred')
    with pytest.raises(ValueError, match='bsf8'):
        refuse_deferral(before, change)
    refuse_deferral(before, change | {'status': 'open', 'defer_until': ''})
    refuse_deferral(before, {'labels': ['technical']})


def test_decision_stiwi_is_ask_and_producer_label_update_refuses_before_write():
    assert is_ask({'labels': ['decision-stiwi']})
    tracker = Mock()
    tracker.get.return_value = WorkItem('lab-1', title='Technical control', status='deferred')
    execute = Mock()
    with pytest.raises(ValueError, match='bsf8'):
        producer_capacity.run(['update', 'lab-1', '--add-label', 'decision-stiwi'], tracker, execute, Mock())
    execute.assert_not_called()


@pytest.mark.parametrize('labels', [{'desk': False}, {'desk': True}, {'needs-stiwi': False},
                                   {'name': 'desk'}, [{'name': ['desk']}], 42])
def test_malformed_label_shapes_do_not_imply_a_human_decision(labels):
    assert not is_ask({'title': 'Ordinary work', 'labels': labels})


def test_valid_ask_marker_still_blocks_deferral_amid_unknown_entries():
    item = {'title': 'Ordinary title', 'labels': ['desk', {}]}
    assert is_ask(item)
    with pytest.raises(ValueError, match='bsf8'):
        refuse_deferral(item, {'status': 'deferred'})
