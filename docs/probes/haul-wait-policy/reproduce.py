"""Run against either package revision using PYTHONPATH; private FilesTracker only."""
import argparse
import tempfile
from pathlib import Path

from shantytown.dispatch import Dispatcher, DeferRefused
from shantytown.feed_check import haul_resume_message
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.tmux import NullPanes
from shantytown.tracker_examples import TrackerExamples

p = argparse.ArgumentParser()
p.add_argument('--expect-deferred', action='store_true', help='baseline behavior')
a = p.parse_args()
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    tracker = FilesTracker(root / 'items')
    tracker.update('sample-1', title='CI wait', status='in_progress', priority=0,
                   assignee='worker')
    dispatch = Dispatcher(FilesRegistry(root / 'crew'), tracker, NullPanes())
    print('P0: defer external, ci-terminal exact head, 2099 backstop')
    try:
        dispatch.defer('sample-1', 'external',
                       'resume_when: ci-terminal:github/example/project@' + 'a' * 40,
                       until='2099-01-01T00:00:00Z')
        outcome = 'deferred'
    except DeferRefused as error:
        outcome = 'refused'
        print(error)
    print('result:', outcome, '| status:', tracker.get('sample-1').status)
    assert outcome == ('deferred' if a.expect_deferred else 'refused')
    text = haul_resume_message('sample-1', 'CI wait', examples=TrackerExamples(('sd',)))
    print('resume prompt recommends defer:', 'st work defer' in text)
    assert ('st work defer' in text) is a.expect_deferred
    tracker.update('sample-2', title='calendar', status='in_progress')
    dispatch.defer('sample-2', 'external', 'scheduled review appointment',
                   until='2099-01-01T00:00:00Z', window=True)
    print('positive control: explicit scheduled appointment:', tracker.get('sample-2').status)
