"""st asks sd for expired mail only where old mail must stay visible (aegis-9qx)."""
import json
from types import SimpleNamespace

from shantytown.sd import SdTracker


def _tracker(answers):
    calls = []
    tracker = object.__new__(SdTracker)

    def bd(*args):
        calls.append(list(args))
        return answers.pop(0)

    tracker._bd = bd
    return tracker, calls


def _ok(rows):
    return SimpleNamespace(returncode=0, stdout=json.dumps(rows), stderr="")


def test_include_expired_adds_the_flag_and_names_the_scope():
    tracker, calls = _tracker([_ok([{"id": "msg-1", "to": "wu"}])])
    answer = tracker.list_messages("wu", unread=False, all_windows=True, include_expired=True)
    assert calls == [["msg", "list", "--to", "wu", "--all-windows", "--json", "--include-expired"]]
    assert answer.exact() == [{"id": "msg-1", "to": "wu"}]


def test_live_reads_never_ask_for_expired_mail():
    tracker, calls = _tracker([_ok([])])
    tracker.list_messages("wu", unread=True, all_windows=True)
    assert "--include-expired" not in calls[0]


def test_an_sd_without_expiry_is_read_again_without_the_flag():
    # An older sd refuses the unknown flag; it also hides nothing, so the
    # plain read is complete and is used instead of failing the lookup.
    refused = SimpleNamespace(returncode=2, stdout="",
                              stderr="error: unexpected argument '--include-expired' found")
    tracker, calls = _tracker([refused, _ok([{"id": "msg-2", "to": "wu"}])])
    answer = tracker.list_messages("wu", unread=False, all_windows=True, include_expired=True)
    assert calls[1] == ["msg", "list", "--to", "wu", "--all-windows", "--json"]
    assert answer.exact() == [{"id": "msg-2", "to": "wu"}]


def test_other_failures_still_refuse():
    broken = SimpleNamespace(returncode=1, stdout="", stderr="quipu unreachable")
    tracker, calls = _tracker([broken])
    try:
        tracker.list_messages("wu", unread=False, all_windows=True, include_expired=True)
    except RuntimeError as error:
        assert "quipu unreachable" in str(error)
    else:
        raise AssertionError("an unreadable mailbox must refuse")
    assert len(calls) == 1
