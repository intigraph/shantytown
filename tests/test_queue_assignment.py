"""aegis-6vto.5 amendment (Stiwi 2026-11-16): assignment, not only dispatch,
must respect board rank; an out-of-order assignment needs a recorded override."""
from types import SimpleNamespace
import json

import pytest

from shantytown import cli, queue_policy, work_item
from shantytown.feed_audit import FeedAudit
from shantytown.protocols import WorkItem

from test_queue_commands import Native, operator_policy  # noqa: F401  (fixture)


def row(ident, lane='next', rank='1', assignee=None, status='open', **extra):
    return dict(id=ident, title='work', status=status, assignee=assignee,
                priority=2, rank=rank, lane=lane) | extra


def audit_states(tmp_path):
    path = FeedAudit(tmp_path).path
    if not path.exists():
        return []
    return [json.loads(line)['state'] for line in path.read_text().splitlines()]


# --- pure policy -----------------------------------------------------------

def test_unranked_or_unlaned_candidate_is_refused():
    for candidate in (row('t-1', rank=None), row('t-1', lane=None), row('t-1', lane='later')):
        assert 'no Now/Next rank' in queue_policy.assignment_refusal(candidate, [], 'ellie')


def test_candidate_below_an_unassigned_item_names_it():
    rows = [row('t-top', rank='1'), row('t-1', rank='5')]
    reason = queue_policy.assignment_refusal(row('t-1', rank='5'), rows, 'ellie')
    assert 't-top' in reason and 'ranks below unassigned' in reason


def test_now_unassigned_outranks_any_next_candidate():
    rows = [row('t-now', lane='now', rank='9')]
    assert 't-now' in queue_policy.assignment_refusal(row('t-1', rank='0'), rows, 'ellie')
    assert not queue_policy.assignment_refusal(row('t-1', lane='now', rank='1'), rows, 'ellie')


def test_in_order_assigned_blocked_and_self_rows_do_not_refuse():
    rows = [row('t-1', rank='5'),
            row('t-taken', rank='1', assignee='wu'),
            row('t-wip', rank='1', status='in_progress'),
            row('t-blocked', rank='1', labels=['blocked:human']),
            row('t-later', rank='6')]
    assert not queue_policy.assignment_refusal(row('t-1', rank='5'), rows, 'ellie')


def test_reassigning_to_the_current_owner_is_not_an_assignment():
    rows = [row('t-top', rank='1')]
    assert not queue_policy.assignment_refusal(
        row('t-1', rank=None, assignee='crew/ellie'), rows, 'ellie')


def test_unreadable_board_refuses_and_cannot_be_overridden(tmp_path):
    class Broken:
        def queue_rows(self):
            raise RuntimeError('incomplete')
    with pytest.raises(ValueError, match='UNKNOWN'):
        queue_policy.assignment(Broken(), row('t-1', rank='1'), 'ellie',
                                reason='urgent', audit=FeedAudit(tmp_path))
    assert audit_states(tmp_path) == ['queue_order_unknown']


def test_override_requires_reason_and_is_counted_with_refusals(tmp_path):
    tracker = Native(); tracker.rows = [row('t-top', rank='1')]
    audit = FeedAudit(tmp_path)
    with pytest.raises(ValueError, match='ranks below'):
        queue_policy.assignment(tracker, row('t-1', rank='5'), 'ellie', audit=audit)
    with pytest.raises(ValueError, match='non-empty reason'):
        queue_policy.assignment(tracker, row('t-1', rank='5'), 'ellie', reason='  ')
    record = json.loads(queue_policy.assignment(tracker, row('t-1', rank='5'), 'ellie',
        reason='operator ruling c12', actor='sattler', audit=audit))
    assert record['schema'] == 'queue-override/v1' and record['actor'] == 'sattler'
    assert 't-top' in record['refusal']
    report = queue_policy.observations(tmp_path)
    assert report['status'] == 'OBSERVED'
    assert report['out_of_order_attempts'] == 1 and report['out_of_order_overrides'] == 1


# --- st work item update ----------------------------------------------------

def update_args(tmp_path, **fields):
    return SimpleNamespace(item='t-1', item_action='update', dry_run=False,
        assignee='ellie', root=tmp_path, **fields)


def board(*rows):
    tracker = Native()
    tracker.items['t-1'] = WorkItem('t-1', lane='next', rank='5', revision=2)
    tracker.rows = [row('t-1', rank='5'), *rows]
    return tracker


def test_update_assignment_refused_without_override_and_no_write(tmp_path, monkeypatch):
    monkeypatch.setenv('SHANTY_QUEUE_POLICY', 'enforce')
    tracker = board(row('t-top', rank='1'))
    with pytest.raises(ValueError, match='t-top'):
        work_item.command(update_args(tmp_path), tracker)
    assert not tracker.writes
    assert audit_states(tmp_path) == ['queue_order_refused']


def test_update_override_records_reason_on_the_transition(tmp_path, monkeypatch):
    monkeypatch.setenv('SHANTY_QUEUE_POLICY', 'enforce')
    tracker = board(row('t-top', rank='1'))
    result = work_item.command(update_args(tmp_path, queue_override='P0 incident'), tracker)
    assert result['result'] == 'verified'
    fields = tracker.writes[0][2]
    assert fields['assignee'] == 'ellie' and fields['if_revision'] == 2
    assert json.loads(fields['transition_comment'])['reason'] == 'P0 incident'
    assert audit_states(tmp_path) == ['queue_order_override']


def test_update_in_order_assignment_writes_no_override(tmp_path, monkeypatch):
    monkeypatch.setenv('SHANTY_QUEUE_POLICY', 'enforce')
    tracker = board(row('t-after', rank='9'))
    work_item.command(update_args(tmp_path), tracker)
    assert 'transition_comment' not in tracker.writes[0][2]
    assert audit_states(tmp_path) == []


def test_off_mode_is_a_no_op_and_rejects_a_stray_override(tmp_path, monkeypatch):
    monkeypatch.setenv('SHANTY_QUEUE_POLICY', 'off')
    tracker = board(row('t-top', rank='1'))
    def forbidden():
        raise AssertionError('off mode must not read the queue')
    tracker.queue_rows = forbidden
    work_item.command(update_args(tmp_path, if_revision=2), tracker)
    assert tracker.writes[0][2]['assignee'] == 'ellie'
    with pytest.raises(ValueError, match='only when the queue policy is enforce'):
        work_item.command(update_args(tmp_path, queue_override='x'), board())


# --- st task -a -------------------------------------------------------------

def task(monkeypatch, tmp_path, tracker, *extra):
    monkeypatch.setenv('SHANTY_QUEUE_POLICY', 'enforce')
    monkeypatch.setattr(cli, '_tracker', lambda a: tracker)
    return cli.main(['--root', str(tmp_path), 'task', 'new ask', *extra])


def test_task_assignee_behind_unassigned_work_is_created_unassigned(monkeypatch, tmp_path, capsys):
    tracker = Native(); tracker.rows = [row('t-top', rank='1')]
    assert task(monkeypatch, tmp_path, tracker, '-a', 'ellie') == cli.REFUSED
    create = tracker.writes[0]
    assert create[0] == 'create' and create[2]['assignee'] is None
    assert tracker.items['test-new'].lane == 'next' and tracker.items['test-new'].assignee is None
    assert 't-top' in capsys.readouterr().err


def test_task_override_assigns_with_recorded_reason(monkeypatch, tmp_path, capsys):
    tracker = Native(); tracker.rows = [row('t-top', rank='1')]
    assert task(monkeypatch, tmp_path, tracker, '-a', 'ellie',
                '--queue-override', 'Stiwi asked directly') == cli.OK
    last = tracker.writes[-1]
    assert last[0] == 'update' and last[2]['assignee'] == 'ellie'
    assert json.loads(last[2]['transition_comment'])['reason'] == 'Stiwi asked directly'
    assert tracker.items['test-new'].assignee == 'ellie'


def test_task_assignee_on_empty_next_is_in_order(monkeypatch, tmp_path):
    tracker = Native()
    assert task(monkeypatch, tmp_path, tracker, '-a', 'ellie') == cli.OK
    assert tracker.writes[0][2]['assignee'] == 'ellie'


def test_task_dry_run_reports_refusal_without_audit_or_write(monkeypatch, tmp_path, capsys):
    tracker = Native(); tracker.rows = [row('t-top', rank='1')]
    assert task(monkeypatch, tmp_path, tracker, '-a', 'ellie', '--dry-run') == cli.OK
    assert tracker.writes == [] and audit_states(tmp_path) == []
    assert 'would refuse assignment' in capsys.readouterr().err


# --- st go ------------------------------------------------------------------

def test_dispatch_heading_own_plate_still_refused_below_unassigned_now(tmp_path):
    tracker = Native()
    tracker.rows = [row('t-top', lane='now', rank='1')]
    target = WorkItem('t-1', lane='now', rank='2')
    reason = queue_policy.gate(tracker, audit=FeedAudit(tmp_path))(target, 'ellie')
    assert 't-top' in reason
    assert audit_states(tmp_path) == ['queue_order_refused']


def test_dispatch_of_already_owned_item_skips_board_check(tmp_path):
    tracker = Native()
    tracker.rows = [row('t-top', lane='now', rank='1')]
    target = WorkItem('t-1', lane='now', rank='2', assignee='ellie')
    assert not queue_policy.gate(tracker)(target, 'ellie')


# --- aegis-jve: a busy quipu is transient, not a hard UNKNOWN --------------

class Busy:
    def __init__(self, message='HTTP Error 408: Request Timeout'):
        self.message = message

    def queue_rows(self):
        raise RuntimeError(self.message)

    def queue_owner_rows(self, owner):
        raise RuntimeError(self.message)


@pytest.mark.parametrize('message', ['HTTP Error 408: Request Timeout',
                                     'status 503 Service Unavailable',
                                     'code=429 too many requests', 'read timed out'])
def test_busy_board_allows_a_recorded_override(tmp_path, message):
    audit = FeedAudit(tmp_path)
    with pytest.raises(ValueError, match='quipu busy.*--queue-override'):
        queue_policy.assignment(Busy(message), row('t-1', rank='1'), 'ellie', audit=audit)
    record = json.loads(queue_policy.assignment(Busy(message), row('t-1', rank='1'), 'ellie',
        reason='quipu busy, operator ruling', actor='sattler', audit=audit))
    assert record['schema'] == 'queue-override/v1' and 'quipu busy' in record['refusal']
    assert audit_states(tmp_path) == ['queue_order_unknown', 'queue_order_unknown_override']
    report = queue_policy.observations(tmp_path)
    assert report['status'] == 'PARTIAL'
    assert report['out_of_order_overrides'] == 1 and report['unknown_attempts'] == 2


def test_non_busy_unreadable_board_stays_non_overridable(tmp_path):
    # An identifier that merely contains a busy code is not an HTTP busy signal.
    for message in ('projection coverage UNKNOWN', 'aegis-503 incomplete'):
        with pytest.raises(ValueError, match='UNKNOWN') as refused:
            queue_policy.assignment(Busy(message), row('t-1', rank='1'), 'ellie',
                                    reason='urgent', audit=FeedAudit(tmp_path))
        assert 'quipu busy' not in str(refused.value)
    assert audit_states(tmp_path) == ['queue_order_unknown', 'queue_order_unknown']


def test_busy_dispatch_is_labelled_retryable_not_a_hard_unknown(tmp_path):
    target = WorkItem('t-1', lane='now', rank='2')
    reason = queue_policy.gate(Busy(), audit=FeedAudit(tmp_path))(target, 'ellie')
    assert 'quipu busy' in reason and 'retry' in reason
    hard = queue_policy.gate(Busy('incomplete'), audit=FeedAudit(tmp_path))(target, 'ellie')
    assert 'quipu busy' not in hard and 'no dispatch' in hard
    assert audit_states(tmp_path) == ['queue_order_busy', 'queue_order_unknown']
    assert queue_policy.observations(tmp_path)['unknown_attempts'] == 2
