"""[inbox] store = "message-graph" (aegis-snq): new mail goes to message windows
through `sd msg`, never to a board seed; readers union legacy seeds + windows."""
from pathlib import Path

import pytest

from shantytown.config import ConfigError, load_or_default
from shantytown.inbox import Message, MessageGraphInbox


class FakeMsgTracker:
    """Speaks the three `sd msg` calls; records them; never creates a seed."""

    def __init__(self):
        self.msgs = []      # dicts as `sd msg list --json` returns them
        self.sent = []
        self.read_calls = []
        self.created = []

    def create(self, *a, **k):  # a seed write would land here
        self.created.append((a, k))
        raise AssertionError("message-graph inbox must not create a seed")

    def send_message(self, to, body, *, key, frm=None, kind="note"):
        self.sent.append((to, body, key, frm))
        mid = "msg-" + str(abs(hash(key)))[:10]
        if not any(m["id"] == mid for m in self.msgs):
            self.msgs.append({"id": mid, "to": to, "from": frm, "text": body, "read_at": None})
        return {"id": mid, "written": True}

    def list_messages(self, to, *, unread=True, weeks=2):
        return [dict(m) for m in self.msgs
                if m["to"] == to and (not unread or m["read_at"] is None)]

    def read_messages(self, ids, *, weeks=2):
        self.read_calls.append(list(ids))
        for m in self.msgs:
            if m["id"] in ids and m["read_at"] is None:
                m["read_at"] = "2026-11-02T05:00:00Z"
        return [{"id": i, "marked": True} for i in ids]


class FakeLegacy:
    """The TrackerInbox surface MessageGraphInbox delegates to."""

    def __init__(self, unread):
        self._unread = list(unread)
        self.marked = []

    def unread(self, me):
        return [m for m in self._unread if not m.read]

    def unread_count(self, me):
        return len(self.unread(me))

    def unread_view(self, me, *, limit=100, oldest_first=False):
        u = self.unread(me)
        return len(u), u[:limit]

    def unread_selected(self, me, ids):
        return [m for m in self.unread(me) if m.id in ids]

    def find_delivery(self, me, marker):
        return None

    def mark_read(self, me, ids=None):
        hit = [m for m in self.unread(me) if ids is None or m.id in ids]
        self.marked += [m.id for m in hit]
        self._unread = [m for m in self._unread if m.id not in {h.id for h in hit}]
        return [Message(id=m.id, to=m.to, body=m.body, read=True) for m in hit]


def _box(legacy_unread=()):
    trk = FakeMsgTracker()
    return MessageGraphInbox(FakeLegacy(legacy_unread), trk), trk


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


def test_unread_unions_legacy_seeds_and_window_messages():
    legacy = [Message(id="aegis-w1", to="wu", body="old seed mail")]
    box, _ = _box(legacy)
    box.deliver("wu", "new window mail", frm="grant")
    box.deliver("tim", "not for wu", frm="grant")
    ids = [m.id for m in box.unread("wu")]
    assert ids[0] == "aegis-w1" and len(ids) == 2 and ids[1].startswith("msg-")
    assert box.unread_count("wu") == 2
    total, view = box.unread_view("wu", limit=1, oldest_first=True)
    assert total == 2 and [m.id for m in view] == ["aegis-w1"]


def test_mark_read_closes_legacy_seeds_and_marks_window_messages():
    legacy = [Message(id="aegis-w1", to="wu", body="old")]
    box, trk = _box(legacy)
    new = box.deliver("wu", "new", frm="grant")
    marked = box.mark_read("wu", ["aegis-w1", new.id])
    assert {m.id for m in marked} == {"aegis-w1", new.id}
    assert box._legacy.marked == ["aegis-w1"]
    assert trk.read_calls == [[new.id]]
    assert box.unread("wu") == []
    # Marking an already-read window message again is a quiet no-op.
    assert box.mark_read("wu", [new.id]) == []
    # A window id that is not this recipient's is refused, nothing marked.
    other = box.deliver("tim", "x", frm="grant")
    with pytest.raises(RuntimeError):
        box.mark_read("wu", [other.id])


def test_mark_all_read_covers_both_stores():
    box, trk = _box([Message(id="aegis-w1", to="wu", body="old")])
    box.deliver("wu", "new", frm="grant")
    assert len(box.mark_read("wu")) == 2
    assert box.unread_count("wu") == 0


def test_find_delivery_reads_windows_first_then_legacy():
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
