"""[inbox] store = "message-graph": new mail goes to message windows
through `sd msg`, never to a board seed, and is read only from the windows
(the legacy-seed dual read was dropped in rollout phase 5)."""
from pathlib import Path

import pytest

from shantytown.answer import Answer, PartialAnswer
from shantytown.config import ConfigError, load_or_default
from shantytown.inbox import Message, MessageGraphInbox


class FakeMsgTracker:
    """Speaks the three `sd msg` calls; records them; never creates a seed."""

    def __init__(self):
        self.msgs = []      # dicts as `sd msg list --json` returns them
        self.sent = []
        self.read_calls = []
        self.created = []
        self.list_calls = []
        self.show_calls = []

    def create(self, *a, **k):  # a seed write would land here
        self.created.append((a, k))
        raise AssertionError("message-graph inbox must not create a seed")

    def send_message(self, to, body, *, key, frm=None, kind="note"):
        self.sent.append((to, body, key, frm))
        mid = "msg-" + str(abs(hash(key)))[:10]
        if not any(m["id"] == mid for m in self.msgs):
            self.msgs.append({"id": mid, "to": to, "from": frm, "text": body, "read_at": None})
        return Answer.complete_read({"id": mid, "written": True}, how="fixture delivery")

    def list_messages(self, to, *, unread=True, weeks=2, all_windows=False, include_expired=False):
        self.list_calls.append((to, unread, all_windows))
        self.__dict__.setdefault("expired_calls", []).append(include_expired)
        return Answer.complete_read([dict(m) for m in self.msgs
                if m["to"] == to and (not unread or m["read_at"] is None)], how="fixture messages")

    def get_message(self, ident):
        """`sd msg show ID --all-windows`: exact, read or unread; unknown id fails."""
        self.show_calls.append(ident)
        for m in self.msgs:
            if m["id"] == ident:
                return Answer.complete_read(dict(m), how="fixture exact receipt")
        raise RuntimeError("sd msg show failed: no such message")

    def read_messages(self, ids, *, weeks=2, all_windows=False):
        self.read_calls.append(list(ids))
        for m in self.msgs:
            if m["id"] in ids and m["read_at"] is None:
                m["read_at"] = "2026-11-02T05:00:00Z"
        return Answer.complete_read([{"id": i, "marked": True} for i in ids], how="fixture read receipts")


def _box():
    trk = FakeMsgTracker()
    return MessageGraphInbox(trk), trk


def test_delivery_goes_to_a_message_window_never_a_seed():
    box, trk = _box()
    m = box.deliver("wu", "hello", frm="grant")
    assert m.id.startswith("msg-") and not m.read
    assert trk.created == [] and len(trk.sent) == 1
    once = box.deliver_once("wu", "again", key="k-1", frm="grant")
    assert box.deliver_once("wu", "again", key="k-1", frm="grant").id == once.id
    assert [s[2] for s in trk.sent][1:] == ["k-1", "k-1"]
    with pytest.raises(ValueError):
        box.deliver_once("wu", "x", key="bad key!")


def test_unread_reads_only_window_messages_for_this_recipient():
    box, trk = _box()
    first = box.deliver("wu", "older window mail", frm="grant")
    second = box.deliver("wu", "newer window mail", frm="grant")
    box.deliver("tim", "not for wu", frm="grant")
    assert [m.id for m in box.unread("wu")] == [first.id, second.id]
    assert box.unread_count("wu") == 2
    total, view = box.unread_view("wu", limit=1)
    assert total == 2 and [m.id for m in view] == [second.id]
    total, view = box.unread_view("wu", limit=1, oldest_first=True)
    assert total == 2 and [m.id for m in view] == [first.id]
    assert trk.created == []


@pytest.mark.parametrize("operation", ["mark_read", "unread_selected", "get_message",
                                       "find_delivery_receipt"])
def test_a_board_seed_id_is_refused_never_resolved_against_the_board(operation):
    """Phase 5: no dual read. A legacy seed id must not be silently skipped
    (an ack would report success) nor read as absent (a receipt check would
    authorize a resend); it is refused before anything is marked."""
    box, trk = _box()
    mine = box.deliver("wu", "window mail", frm="grant")
    call = {"mark_read": lambda: box.mark_read("wu", [mine.id, "aegis-w1"]),
            "unread_selected": lambda: box.unread_selected("wu", ["aegis-w1"]),
            "get_message": lambda: box.get_message("wu", "aegis-w1"),
            "find_delivery_receipt": lambda: box.find_delivery_receipt("wu", "M", "aegis-w1")}
    with pytest.raises(RuntimeError, match="not a message-window id"):
        call[operation]()
    assert trk.read_calls == [] and trk.show_calls == [] and box.unread_count("wu") == 1


def test_mark_read_marks_window_messages_append_only():
    box, trk = _box()
    new = box.deliver("wu", "new", frm="grant")
    marked = box.mark_read("wu", [new.id])
    assert [m.id for m in marked] == [new.id] and marked[0].read
    assert trk.read_calls == [[new.id]]
    assert box.unread("wu") == []
    # Marking an already-read window message again is a quiet no-op.
    assert box.mark_read("wu", [new.id]) == []
    # A window id that is not this recipient's is refused, nothing marked.
    other = box.deliver("tim", "x", frm="grant")
    with pytest.raises(RuntimeError):
        box.mark_read("wu", [other.id])


def test_mark_all_read_marks_every_window_message():
    box, trk = _box()
    box.deliver("wu", "one", frm="grant")
    box.deliver("wu", "two", frm="grant")
    assert len(box.mark_read("wu")) == 2
    assert box.unread_count("wu") == 0


def test_find_delivery_reads_windows_only():
    box, _ = _box()
    box.deliver_once("wu", "MARK-1 body", key="k1", frm="grant")
    assert box.find_delivery("wu", "MARK-1").body == "MARK-1 body"
    assert box.find_delivery("wu", "MARK-2") is None


def _cfg(tmp_path: Path, text: str):
    (tmp_path / "shantytown.toml").write_text(text)
    return load_or_default(tmp_path)


def test_inbox_store_defaults_to_seed_and_accepts_message_graph(tmp_path):
    cfg, err = _cfg(tmp_path, "")
    assert err is None and cfg.inbox_store == "seed"
    cfg, err = _cfg(tmp_path, '[inbox]\nstore = "message-graph"\n')
    assert err is None and cfg.inbox_store == "message-graph"


def test_inbox_store_refuses_unknown_values_and_keys(tmp_path):
    _, err = _cfg(tmp_path, '[inbox]\nstore = "graph"\n')
    assert err and "inbox.store" in err
    _, err = _cfg(tmp_path, '[inbox]\nttl = 3\n')
    assert err


def test_partial_message_listing_cannot_become_an_empty_inbox(monkeypatch):
    box, trk = _box()
    monkeypatch.setattr(trk, "list_messages", lambda *a, **k: Answer.capped(
        [], how="truncated fixture", caveat="server row cap"))
    with pytest.raises(PartialAnswer):
        box.unread_count("wu")
    with pytest.raises(PartialAnswer):
        box.find_delivery("wu", "marker")


def test_partial_read_receipt_cannot_be_reported_as_marked(monkeypatch):
    box, trk = _box()
    message = box.deliver("wu", "hello")
    monkeypatch.setattr(trk, "read_messages", lambda *a, **k: Answer.capped(
        [], how="missing receipt", caveat="incomplete read"))
    with pytest.raises(PartialAnswer):
        box.mark_read("wu", [message.id])


@pytest.mark.parametrize("receipt", [[], [{"id": "msg-one", "marked": True}],
    [{"id": "msg-one", "marked": True}, {"id": "msg-one", "marked": True}],
    [{"id": "msg-one", "marked": True}, {"id": "msg-two", "marked": "yes"}]])
def test_sd_read_requires_a_typed_receipt_for_every_requested_id(receipt):
    import json
    from types import SimpleNamespace
    from shantytown.sd import SdTracker
    tracker = object.__new__(SdTracker)
    tracker._bd = lambda *args: SimpleNamespace(returncode=0, stdout=json.dumps(receipt), stderr="")
    with pytest.raises(RuntimeError, match="receipts incomplete or unreadable"):
        tracker.read_messages(["msg-one", "msg-two"])


def test_sd_read_accepts_complete_receipts_including_already_read():
    import json
    from types import SimpleNamespace
    from shantytown.sd import SdTracker
    receipt = [{"id": "msg-one", "marked": True}, {"id": "msg-two", "marked": False}]
    tracker = object.__new__(SdTracker)
    tracker._bd = lambda *args: SimpleNamespace(returncode=0, stdout=json.dumps(receipt), stderr="")
    assert tracker.read_messages(["msg-one", "msg-two"]).exact() == receipt


@pytest.mark.parametrize("operation", ["unread", "unread_count", "unread_view", "unread_selected", "mark_read"])
def test_mail_older_than_two_weeks_remains_visible_and_acknowledgeable(operation):
    box, tracker = _box()
    old = {"id": "msg-old-live-window", "to": "wu", "text": "old unread",
           "sent_at": "2025-12-22T10:00:00Z", "read_at": None}
    calls = []
    def listing(to, *, unread=True, weeks=2, all_windows=False):
        calls.append(all_windows)
        return Answer.complete_read([old] if all_windows else [], how="age-aware window fixture")
    tracker.list_messages = listing
    tracker.msgs.append(old)
    if operation == "unread":
        assert [m.id for m in box.unread("wu")] == [old["id"]]
    elif operation == "unread_count":
        assert box.unread_count("wu") == 1
    elif operation == "unread_view":
        count, rows = box.unread_view("wu")
        assert count == 1 and rows[0].id == old["id"]
    elif operation == "unread_selected":
        assert box.unread_selected("wu", [old["id"]])[0].id == old["id"]
    else:
        # A named acknowledgment reads the exact receipt (`sd msg show
        # --all-windows`), so an old live window is still acknowledgeable.
        assert box.mark_read("wu", [old["id"]])[0].id == old["id"]
        assert tracker.show_calls == [old["id"]] and not calls
        return
    assert calls and all(calls)


def test_sdk_all_window_scope_is_explicit_for_listing_and_acknowledgment():
    import json
    from types import SimpleNamespace
    from shantytown.sd import SdTracker
    tracker = object.__new__(SdTracker)
    calls = []
    def bd(*args):
        calls.append(args)
        value = [] if args[1] == "list" else [{"id": "msg-old", "marked": True}]
        return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="")
    tracker._bd = bd
    assert tracker.list_messages("wu", all_windows=True).exact() == []
    assert tracker.read_messages(["msg-old"], all_windows=True).exact()[0]["marked"]
    assert all("--all-windows" in args and "--weeks" not in args for args in calls)


def test_unsupported_all_window_scope_refuses_without_recent_window_retry():
    from types import SimpleNamespace
    from shantytown.sd import SdTracker
    tracker = object.__new__(SdTracker)
    calls = []
    def bd(*args):
        calls.append(args)
        return SimpleNamespace(returncode=2, stdout="", stderr="unknown --all-windows")
    tracker._bd = bd
    with pytest.raises(RuntimeError, match="sd msg list failed"):
        tracker.list_messages("wu", all_windows=True)
    assert len(calls) == 1


def test_named_acknowledgment_reads_exact_receipts_not_every_window():
    """aegis-xdvg.4: closing one delivery pointer must not list every window twice."""
    box, trk = _box()
    first = box.deliver("wu", "one", frm="grant")
    second = box.deliver("wu", "two", frm="grant")
    trk.list_calls.clear()
    marked = box.mark_read("wu", [first.id, second.id])
    assert {m.id for m in marked} == {first.id, second.id}
    assert trk.list_calls == [] and trk.show_calls == [first.id, second.id]
    assert trk.read_calls == [[first.id, second.id]]
    # Already read: exact receipt shows read_at, quiet no-op, no second mark.
    trk.show_calls.clear()
    assert box.mark_read("wu", [first.id]) == [] and trk.read_calls == [[first.id, second.id]]


@pytest.mark.parametrize("case", ["missing", "foreign"])
def test_exact_acknowledgment_refuses_before_marking_anything(case):
    box, trk = _box()
    mine = box.deliver("wu", "mine", frm="grant")
    bad = "msg-does-not-exist" if case == "missing" else box.deliver("tim", "x", frm="grant").id
    with pytest.raises(RuntimeError, match="refused inbox acknowledgment"):
        box.mark_read("wu", [mine.id, bad])
    assert trk.read_calls == [] and box.unread_count("wu") == 1


def test_unreadable_exact_receipt_is_unknown_not_marked(monkeypatch):
    box, trk = _box()
    mine = box.deliver("wu", "mine", frm="grant")
    def broken(ident):
        raise RuntimeError("sd msg show failed: transport timeout")
    monkeypatch.setattr(trk, "get_message", broken)
    with pytest.raises(RuntimeError, match="exact receipt UNKNOWN"):
        box.mark_read("wu", [mine.id])
    assert trk.read_calls == []


def test_many_named_ids_keep_the_two_listing_path():
    box, trk = _box()
    ids = [box.deliver("wu", f"m{i}", frm="grant").id for i in range(MessageGraphInbox.EXACT_ACK_LIMIT + 1)]
    trk.list_calls.clear()
    assert len(box.mark_read("wu", ids)) == len(ids)
    assert trk.show_calls == []
    assert trk.list_calls == [("wu", True, True), ("wu", False, True)]


def test_unread_reads_live_windows_and_lets_sd_expire_old_mail():
    # aegis-9qx: unread counts and listings never ask for expired mail; sd's
    # TTL (seeds [msg] ttl, default 7 days) decides what is live.
    box, trk = _box()
    box.deliver("wu", "fresh", "sattler")
    assert box.unread_count("wu") == 1
    box.unread("wu")
    assert trk.expired_calls and not any(trk.expired_calls)


def test_delivery_lookups_include_expired_mail_so_old_keys_are_never_resent():
    box, trk = _box()
    sent = box.deliver_once("wu", "MARK-1 body", key="k-1", frm="sattler")
    assert box.find_delivery("wu", "MARK-1") == sent
    assert box.find_delivery_receipt("wu", "MARK-1", sent.id) == sent
    assert trk.expired_calls == [True, True]
