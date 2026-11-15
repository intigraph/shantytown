from dataclasses import replace
from types import SimpleNamespace
import json

import pytest

from shantytown import cli, queue_policy, work_item
from shantytown.protocols import WorkItem
from shantytown.sd import SdTracker
from shantytown.feed_audit import FeedAudit


class Native(SdTracker):
    def __init__(self):
        self.rows = []
        self.items = {}
        self.writes = []
        self.fail = None

    def queue_rows(self):
        return self.rows.copy()

    def queue_owner_rows(self, owner):
        return self.rows.copy()

    def capacity_admission_rows(self, owner):
        from shantytown.answer import Answer
        return Answer.complete_read([r for r in self.rows if r.get('assignee') == owner],
                                    how='private capacity fixture')

    capacity_rows = capacity_admission_rows

    def create(self, title, **fields):
        self.writes.append(('create', title, fields))
        result = WorkItem('test-new', title=title, revision=1)
        self.items[result.id] = result
        return result

    def get(self, ident):
        return self.items[ident]

    def update(self, ident, **fields):
        self.writes.append(('update', ident, fields))
        assert fields['if_revision'] == self.items[ident].revision
        if self.fail:
            raise self.fail
        clean = {k: v for k, v in fields.items() if k not in ('if_revision', 'transition_comment')}
        self.items[ident] = replace(self.items[ident], **clean, revision=self.items[ident].revision + 1)
        self.rows = [r for r in self.rows if r['id'] != ident] + [vars(self.items[ident])]


def task(monkeypatch, tmp_path, tracker, *extra):
    monkeypatch.setenv('SHANTY_QUEUE_POLICY', 'enforce')
    monkeypatch.setattr(cli, '_tracker', lambda a: tracker)
    return cli.main(['--root', str(tmp_path), 'task', 'new work', *extra])


def test_intake_actual_cli_verifies_cas_and_prints_position(monkeypatch, tmp_path, capsys):
    tracker = Native()
    assert task(monkeypatch, tmp_path, tracker) == cli.OK
    assert [c[0] for c in tracker.writes] == ['create', 'update']
    fields = tracker.writes[1][2]
    assert fields['lane'] == 'next' and fields['rank'] == '1'
    assert json.loads(fields['transition_comment'])['schema'] == 'queue-intake/v1'
    assert 'Next position 1' in capsys.readouterr().out


def test_intake_partial_create_prints_id_and_does_not_recreate(monkeypatch, tmp_path, capsys):
    tracker = Native(); tracker.fail = TimeoutError('indeterminate CAS')
    assert task(monkeypatch, tmp_path, tracker) == cli.CANNOT_TELL
    assert [c[0] for c in tracker.writes] == ['create', 'update']
    text = capsys.readouterr().err
    assert 'test-new CREATED' in text and 'do not repeat create' in text


def test_intake_dry_run_has_no_write(monkeypatch, tmp_path):
    tracker = Native()
    assert task(monkeypatch, tmp_path, tracker, '--dry-run') == cli.OK
    assert tracker.writes == []


def test_gate_counts_refused_attempt_and_does_not_weaken_existing_governor(tmp_path):
    tracker = Native(); audit = FeedAudit(tmp_path)
    target = WorkItem('test-new', lane='next', rank='1')
    gate = queue_policy.gate(tracker, audit=audit)
    assert 'not in Now' in gate(target, 'ellie')
    rows = [json.loads(line) for line in audit.path.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]['state'] == 'queue_order_refused'
    assert queue_policy.gate(tracker, lambda *a: 'gaming hold', audit=audit)(target, 'ellie') == 'gaming hold'
    assert len(audit.path.read_text().splitlines()) == 1
    queue_policy.gate(tracker, audit=audit, dry_run=True)(target, 'ellie')
    assert len(audit.path.read_text().splitlines()) == 1


def test_queue_read_failure_refuses_instead_of_using_empty_plate():
    class Partial:
        def queue_owner_rows(self, owner):
            raise RuntimeError('incomplete')
    assert 'UNKNOWN' in queue_policy.gate(Partial())(WorkItem('test-1', lane='now', rank='1'), 'ellie')


def promotion_args(tmp_path, **fields):
    return SimpleNamespace(item='test-1', item_action='update', dry_run=False,
        lane='now', rank='1', quote='Please do it now.', requester='operator',
        urgent=True, root=tmp_path, **fields)


def test_now_promotion_atomic_quote_and_cap_refusal_preserved(tmp_path):
    tracker = Native(); tracker.items['test-1'] = WorkItem('test-1', lane='next', rank='2', revision=3)
    result = work_item.command(promotion_args(tmp_path), tracker)
    assert result['result'] == 'verified'
    fields = tracker.writes[0][2]
    assert fields['if_revision'] == 3 and fields['lane'] == 'now'
    assert json.loads(fields['transition_comment'])['quote'] == 'Please do it now.'


def test_unquoted_promotion_has_no_write(tmp_path):
    tracker = Native(); tracker.items['test-1'] = WorkItem('test-1', lane='next', rank='2', revision=3)
    args = promotion_args(tmp_path); args.quote = ''
    with pytest.raises(ValueError, match='--quote'):
        work_item.command(args, tracker)
    assert not tracker.writes


def test_old_receipt_scope_digest_is_unchanged_by_additive_lane_field():
    from dataclasses import asdict
    from shantytown.dispatch_binding import task_digest, digest
    item = WorkItem('test-1', title='original task', rank='1', lane='now')
    original = {k: v for k, v in asdict(item).items() if k not in {
        'revision', 'status', 'assignee', 'defer_until', 'updated_at', 'lane'}}
    assert task_digest(item) == digest(original)
    assert task_digest(replace(item, rank='2')) != task_digest(item)


def test_observation_missing_malformed_and_retained_scope(tmp_path):
    assert queue_policy.observations(tmp_path)['out_of_order_attempts'] is None
    audit = FeedAudit(tmp_path)
    audit.record('one', leg='queue', worker='ellie', item='test-1', refused=True,
                 state='queue_order_refused', reason='not Now')
    observed = queue_policy.observations(tmp_path)
    assert observed['status'] == 'OBSERVED' and observed['out_of_order_attempts'] == 1
    audit.path.write_text('{malformed\n')
    assert queue_policy.observations(tmp_path)['status'] == 'UNKNOWN'


def test_unknown_ordering_is_not_counted_as_proven_out_of_order(tmp_path):
    audit = FeedAudit(tmp_path)
    queue_policy.gate(Native(), audit=audit)(WorkItem('test-unknown'), 'ellie')
    report = queue_policy.observations(tmp_path)
    assert report['status'] == 'PARTIAL'
    assert report['out_of_order_attempts'] == 0 and report['unknown_attempts'] == 1


def test_quoted_promotion_native_refusal_never_retries(tmp_path):
    tracker = Native(); tracker.items['test-1'] = WorkItem('test-1', lane='next', rank='2', revision=3)
    tracker.fail = RuntimeError('lane now full; displace test-other first')
    with pytest.raises(RuntimeError, match='displace test-other'):
        work_item.command(promotion_args(tmp_path), tracker)
    assert len(tracker.writes) == 1
    assert tracker.items['test-1'].lane == 'next'


def test_dispatch_gate_refuses_before_any_send_or_tracker_write(tmp_path):
    from shantytown.dispatch import Dispatcher, GovernorRefused
    from shantytown.files import FilesRegistry
    from shantytown.tmux import NullPanes
    crew = tmp_path / 'crew'; crew.mkdir()
    (crew / 'ellie.json').write_text(json.dumps({'role': 'worker', 'pane': '%1'}))
    tracker = Native()
    tracker.items['test-1'] = WorkItem('test-1', title='new ask', lane='next', rank='1')
    panes = NullPanes()
    dispatcher = Dispatcher(FilesRegistry(crew), tracker, panes,
                            governor=queue_policy.gate(tracker))
    with pytest.raises(GovernorRefused, match='not in Now'):
        dispatcher.go('test-1', 'ellie')
    assert not panes.sent and not tracker.writes
