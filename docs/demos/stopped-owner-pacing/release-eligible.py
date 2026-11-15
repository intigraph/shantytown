"""Replay the release-eligible pair against an explicit source tree."""
from pathlib import Path
import sys
import tempfile

source = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(source), str(source / 'tests')]
import pytest
from shantytown import deferrals
from shantytown.stopped import FilesStops
from test_deferral_owner_routing import NOW, harness

evaluate, can_release = deferrals.evaluate, deferrals.can_release
with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
    root = Path(directory)
    h = harness(root, patch, priority=4)
    patch.setattr(deferrals, 'evaluate', evaluate)
    patch.setattr(deferrals, 'can_release', can_release)
    rows = [{**h.row, 'id': f'test-lapsed-{n}', 'notes': ''} for n in range(2)]
    by_id = {row['id']: row for row in rows}
    h.alerter._read = lambda: rows
    h.alerter._show = by_id.__getitem__
    released = []
    def release(identifier):
        released.append(identifier)
        by_id[identifier].update(status='open', assignee=None, defer_until=None)
    h.alerter._release = release
    FilesStops(root / 'stopped').record('worker', NOW.timestamp())
    h.alerter.sweep()
    print(f'first: released={len(released)} admin_digests={len(h.admins)} '
          f'lead_wakes={sum(pane == "lead" for pane, _ in h.sent)} '
          f'held={sum(row["status"] == "deferred" for row in rows)}/2')
    h.alerter.sweep()
    print(f'repeat: released={len(released)} admin_digests={len(h.admins)}')
    FilesStops(root / 'stopped').forget('worker')
    h.alerter.sweep()
    print(f'stop_cleared: released={len(released)} admin_digests={len(h.admins)}')
