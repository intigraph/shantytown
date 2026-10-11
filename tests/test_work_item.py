from argparse import Namespace

import pytest

from shantytown.files import FilesTracker
from shantytown.protocols import WorkItem
from shantytown import work_item


def args(item, action, **values):
    return Namespace(item=item, item_action=action, dry_run=False,
                     **values)


def test_files_show_update_comment_close_with_terminal_evidence(tmp_path):
    tracker = FilesTracker(tmp_path / "items")
    item = tracker.create("controlled fixture")
    body = tmp_path / "reason.txt"
    body.write_text("Measured failure 1 -> 0")
    assert work_item.command(args(item.id, "show"), tracker)["id"] == item.id
    work_item.command(args(item.id, "update", status="in_progress"), tracker)
    assert tracker.get(item.id).status == "in_progress"
    work_item.command(args(item.id, "comment", file=body), tracker)
    result = work_item.command(args(item.id, "close", reason_file=body), tracker)
    assert result["result"] == "verified"
    assert tracker.get(item.id).close_reason == body.read_text()


def test_wrong_id_response_refuses_before_any_write():
    class Wrong:
        def get(self, item_id):
            return WorkItem("another-id")
        def update(self, *args, **kwargs):
            pytest.fail("must not write")
    with pytest.raises(ValueError, match="different"):
        work_item.command(args("known-id", "update", status="open"), Wrong())


def test_indeterminate_update_never_retries():
    class Unknown:
        calls = 0
        def get(self, item_id):
            return WorkItem(item_id)
        def update(self, *args, **kwargs):
            self.calls += 1
            raise TimeoutError("may have committed")
    tracker = Unknown()
    with pytest.raises(TimeoutError):
        work_item.command(args("known-id", "update", status="in_progress"), tracker)
    assert tracker.calls == 1


def test_dry_run_close_does_not_touch_terminal_state(tmp_path):
    tracker = FilesTracker(tmp_path / "items")
    item = tracker.create("control")
    body = tmp_path / "reason.txt"; body.write_text("proof")
    values = args(item.id, "close", reason_file=body)
    values.dry_run = True
    work_item.command(values, tracker)
    assert tracker.get(item.id).status == "open"


def test_tracker_protocol_is_still_three_methods():
    from shantytown.protocols import Tracker
    assert {name for name in Tracker.__dict__ if not name.startswith("_")} == {
        "get", "update", "create"}
