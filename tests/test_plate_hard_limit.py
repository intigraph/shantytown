"""Urgency must not give an eleventh real assignment a capacity exemption."""
import pytest

from shantytown.files import FilesTracker
from shantytown.plate_capacity import PlateFull, ensure_room


@pytest.mark.parametrize('priority', [0, 1, 2, 3, 4])
def test_ten_real_items_refuse_every_new_priority(tmp_path, monkeypatch, priority):
    monkeypatch.setenv('HOME', str(tmp_path))
    tracker = FilesTracker(tmp_path / 'items')
    for i in range(10):
        tracker.create(f'Work {i}', assignee='worker')
    with pytest.raises(PlateFull):
        ensure_room(tracker, 'worker', candidate={'title': 'New work', 'priority': priority})
