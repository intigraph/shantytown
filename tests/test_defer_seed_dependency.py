"""Seeds uses an actual dependency, never the refused blocked:bead label."""
import json
import subprocess

import pytest

from shantytown import cli
from shantytown.dispatch import DeferRefused, DeferUnconfirmed
from shantytown.sd import SdTracker
from test_defer_timeout import PartialBr, dispatcher


class Seeds(PartialBr, SdTracker):
    def __init__(self, *, dep_exit=0, observe=True, timeout=False):
        super().__init__()
        self.quipu = None
        self.row.update(status="in_progress", defer_until="2026-12-01")
        self.dep_exit, self.observe, self.timeout = dep_exit, observe, timeout
        self.calls = []
        self.edge = False

    def _bd_for(self, item_id, *args):
        self.calls.append(args)
        assert not any(x.startswith('--add-label=blocked:') for x in args)
        if args[:2] == ('dep', 'add'):
            assert args == ('dep', 'add', 'item-1', 'item-2', '--done-when', 'closed', '--json')
            self.edge = True
            if self.timeout:
                raise subprocess.TimeoutExpired('sd dep add', 30)
            return subprocess.CompletedProcess(args, self.dep_exit, '', 'refused' if self.dep_exit else '')
        if args[:2] == ('dep', 'list'):
            rows = ([dict(issue_id='item-1', depends_on_id='item-2', type='blocks')]
                    if self.edge and self.observe else [])
            return subprocess.CompletedProcess(args, 0, json.dumps(rows), '')
        return super()._bd_for(item_id, *args)


def defer(tmp_path, tracker, **kwargs):
    return dispatcher(tmp_path, tracker).defer('item-1', 'bead',
        'required tested code\nresume_when: closed:item-2',
        dependency_reason='Required tested code path', **kwargs)


def test_date_only_bead_refuses_without_partial_deadline_write(tmp_path):
    tracker = Seeds()
    with pytest.raises(DeferRefused, match='closed:<blocker-id>'):
        dispatcher(tmp_path, tracker).defer('item-1', 'bead', 'wait', until='2026-12-02')
    assert tracker.writes == []
    assert not tracker.edge
    assert tracker.row['defer_until'] == '2026-12-01'


def test_native_dependency_precedes_open_and_clears_date(tmp_path):
    tracker = Seeds()
    tracker.row['labels'] = ['security', 'blocked:external']
    result = defer(tmp_path, tracker)
    assert result.dependency == 'item-2'
    assert tracker.row['status'] == 'open'
    assert not tracker.row['defer_until']
    assert tracker.row['labels'] == ['security']
    assert tracker.calls.index(('dep', 'list', 'item-1', '--json')) < next(
        i for i, call in enumerate(tracker.calls) if call[0] == 'update')
    assert 'resume_when: closed:item-2' in tracker.row['notes']


def test_dry_run_has_no_dependency_or_item_writes(tmp_path):
    tracker = Seeds()
    assert defer(tmp_path, tracker, dry_run=True).dependency == 'item-2'
    assert not tracker.edge and not tracker.writes


@pytest.mark.parametrize('options', [dict(dep_exit=5), dict(observe=False), dict(timeout=True)])
def test_unproven_dependency_never_releases_or_retries(tmp_path, options):
    tracker = Seeds(**options)
    with pytest.raises(DeferUnconfirmed, match='No automatic retry'):
        defer(tmp_path, tracker)
    assert tracker.row['status'] == 'in_progress'
    assert tracker.writes == []
    assert sum(call[:2] == ('dep', 'add') for call in tracker.calls) == 1


def test_cli_reports_dependency_not_label_deferral(tmp_path, monkeypatch, capsys):
    tracker = Seeds()
    monkeypatch.setattr(cli, '_wire', lambda a: dispatcher(tmp_path, tracker))
    assert cli.main(['work', 'defer', 'item-1', 'bead', '--reason',
                     'resume_when: closed:item-2', '--dependency-reason',
                     'Required tested code path']) == cli.OK
    out = capsys.readouterr().out
    assert 'recorded and verified dependency item-1 waits for item-2' in out
    assert 'deferred as blocked:bead' not in out
