"""A CI wake must not hide work or tell an agent to date-defer it."""
from datetime import datetime, timedelta, timezone

import pytest

from shantytown import feed_check
from shantytown.dispatch import DeferRefused, Dispatcher
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.tmux import NullPanes
from shantytown.tracker_examples import TrackerExamples


@pytest.mark.parametrize('message', [feed_check.haul_feed_message, feed_check.haul_resume_message])
def test_haul_wait_guidance_keeps_work_visible(message):
    args = ('item-1', 'work', 0) if message is feed_check.haul_feed_message else ('item-1', 'work')
    text = message(*args, examples=TrackerExamples(argv=('sd',)))
    assert 'CI/review wait: stay in_progress' in text
    assert 'st work defer' not in text
    assert 'dependency edge' in text


@pytest.mark.parametrize('priority', [0, 1, 2])
@pytest.mark.parametrize('dry_run', [False, True])
@pytest.mark.parametrize('reason', [
    'resume_when: ci-terminal:github/example/project@' + 'a' * 40,
    'resume_when: pr-merged:github/example/project#123',
    'Waiting for review\nresume_when: date:2099-01-01T00:00:00Z',
    'CI wait appointment\nresume_when: date:2099-01-01T00:00:00Z',
])
def test_ci_review_wait_refuses_before_any_tracker_write(tmp_path, priority, dry_run, reason):
    tracker = FilesTracker(tmp_path / 'items')
    tracker.update('item-1', title='work', status='in_progress', priority=priority,
                   assignee='worker')
    before = tracker._path('item-1').read_bytes()
    dispatcher = Dispatcher(FilesRegistry(tmp_path / 'crew'), tracker, NullPanes())
    until = (datetime.now(timezone.utc) + timedelta(hours=25)).strftime('%Y-%m-%dT%H:%M:%SZ')
    with pytest.raises(DeferRefused, match='stay in_progress'):
        dispatcher.defer('item-1', 'external', reason, until=until, dry_run=dry_run, window=True)
    assert tracker._path('item-1').read_bytes() == before


@pytest.mark.parametrize('dry_run', [False, True])
def test_existing_ci_deferral_is_not_accepted_as_an_idempotent_noop(tmp_path, dry_run):
    from shantytown.deferral_notes import canonical_reason
    tracker = FilesTracker(tmp_path / 'items')
    reason = 'resume_when: ci-terminal:github/example/project@' + 'a' * 40
    until = '2099-01-01T00:00:00Z'
    tracker.update('item-1', title='work', status='deferred', priority=0,
                   assignee='worker', defer_until=until, labels=['blocked:external'],
                   notes=canonical_reason(reason, reason.removeprefix('resume_when: ')))
    before = tracker._path('item-1').read_bytes()
    dispatcher = Dispatcher(FilesRegistry(tmp_path / 'crew'), tracker, NullPanes())
    with pytest.raises(DeferRefused, match='stay in_progress'):
        dispatcher.defer('item-1', 'external', reason, until=until, dry_run=dry_run)
    assert tracker._path('item-1').read_bytes() == before
