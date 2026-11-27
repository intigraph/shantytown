"""Named, pluggable message backends (aegis-8dda.10.6).

Stiwi 2026-11-27: st "should support a pluggable msg system st agents use and
chaski will be an implementation". One protocol suite runs against every named
backend: a plain in-memory test backend and the Chaski-shaped "message-graph"
backend. The suite is also run against a deliberately broken backend to show it
can say no.
"""
from pathlib import Path

import pytest

from shantytown import inbox as inbox_mod
from shantytown.config import load_or_default
from shantytown.inbox import (INBOX_BACKENDS, Message, TrackerInbox, deliver_notice,
                              open_inbox, register_inbox_backend)
from test_message_graph_inbox import FakeLegacy, FakeMsgTracker


class MemoryInbox:
    """The smallest honest Inbox: a list of dicts."""

    def __init__(self, consume_on_read=False):
        self.rows = []
        self._consume = consume_on_read

    def deliver(self, to, body, frm=None):
        return self._add(to, body, frm, None)

    def deliver_once(self, to, body, key, frm=None):
        for r in self.rows:
            if r["key"] == key:
                return Message(r["id"], r["to"], r["body"], r["frm"], r["read"])
        return self._add(to, body, frm, key)

    def _add(self, to, body, frm, key):
        row = dict(id=f"mem-{len(self.rows) + 1}", to=to, body=body, frm=frm,
                   read=False, key=key)
        self.rows.append(row)
        return Message(row["id"], to, body, frm, False)

    def unread(self, me):
        hit = [r for r in self.rows if r["to"] == me and not r["read"]]
        if self._consume:  # the defect the suite must catch: a read that marks
            for r in hit:
                r["read"] = True
        return [Message(r["id"], r["to"], r["body"], r["frm"], False) for r in hit]

    def mark_read(self, me, ids=None):
        out = []
        for r in self.rows:
            if r["to"] == me and not r["read"] and (ids is None or r["id"] in ids):
                r["read"] = True
                out.append(Message(r["id"], r["to"], r["body"], r["frm"], True))
        return out


@pytest.fixture
def registered():
    names = []

    def add(name, factory):
        register_inbox_backend(name, factory)
        names.append(name)
    yield add
    for n in names:
        INBOX_BACKENDS.pop(n, None)


def protocol_suite(box):
    """The Inbox contract every backend must keep."""
    a = box.deliver("wu", "one", frm="grant")
    b = box.deliver("wu", "two")
    box.deliver("malcolm", "not yours")
    assert {m.id for m in box.unread("wu")} == {a.id, b.id}
    # a pure read: reading twice still shows both, nothing was consumed
    assert {m.id for m in box.unread("wu")} == {a.id, b.id}, "unread() consumed mail"
    marked = box.mark_read("wu", [a.id])
    assert [m.id for m in marked] == [a.id] and all(m.read for m in marked)
    assert [m.id for m in box.unread("wu")] == [b.id]
    first = box.deliver_once("wu", "once", "capacity:x:wu:2026-11-27", frm="st")
    again = box.deliver_once("wu", "once", "capacity:x:wu:2026-11-27", frm="st")
    assert first.id == again.id
    assert sorted(m.id for m in box.unread("wu")) == sorted([b.id, first.id])
    box.mark_read("wu")
    assert box.unread("wu") == []
    assert [m.body for m in box.unread("malcolm")] == ["not yours"]


def _open(name, registered):
    if name == "memory-test":
        registered("memory-test", lambda legacy, tracker: MemoryInbox())
        return open_inbox("memory-test", None, None)
    return open_inbox("message-graph", FakeLegacy(()), FakeMsgTracker())


@pytest.mark.parametrize("name", ["memory-test", "message-graph"])
def test_every_named_backend_passes_the_same_protocol_suite(name, registered):
    box = _open(name, registered)
    assert isinstance(box, inbox_mod.Inbox)
    protocol_suite(box)


def test_the_protocol_suite_fails_a_backend_whose_read_marks(registered):
    registered("consuming", lambda legacy, tracker: MemoryInbox(consume_on_read=True))
    with pytest.raises(AssertionError, match="consumed"):
        protocol_suite(open_inbox("consuming", None, None))


def test_unknown_backend_name_is_refused_not_routed_to_seeds():
    with pytest.raises(ValueError, match="unknown inbox backend 'mesage-graph'"):
        open_inbox("mesage-graph", FakeLegacy(()), FakeMsgTracker())


def test_registering_an_existing_name_is_refused():
    with pytest.raises(ValueError, match="already registered"):
        register_inbox_backend("message-graph", lambda legacy, tracker: MemoryInbox())


def test_message_graph_without_sd_msg_stays_on_seeds():
    legacy = FakeLegacy(())

    class NoMsg:
        pass
    assert open_inbox("message-graph", legacy, NoMsg()) is legacy


def test_config_accepts_a_registered_backend_and_refuses_an_unregistered_one(
        tmp_path, registered):
    (tmp_path / "shantytown.toml").write_text('[inbox]\nstore = "memory-test"\n')
    cfg, err = load_or_default(tmp_path)
    assert err and "inbox.store must be one of" in str(err) and "memory-test" in str(err)
    registered("memory-test", lambda legacy, tracker: MemoryInbox())
    cfg, err = load_or_default(tmp_path)
    assert err is None and cfg.inbox_store == "memory-test"


def test_notice_is_keyed_on_message_graph_and_one_per_key():
    trk = FakeMsgTracker()
    box = open_inbox("message-graph", FakeLegacy(()), trk)
    deliver_notice(box, "lead", "capacity: x", "capacity:x:wu:2026-11-27", frm="st")
    deliver_notice(box, "lead", "capacity: x", "capacity:x:wu:2026-11-27", frm="st")
    assert [s[2] for s in trk.sent] == ["capacity:x:wu:2026-11-27"] * 2
    assert len(box.unread("lead")) == 1


def test_notice_on_a_seed_tracker_without_stable_create_stays_unkeyed():
    created = []

    class Plain:
        def create(self, title, **fields):
            created.append((title, fields))
            from shantytown.protocols import WorkItem
            return WorkItem(id="aegis-1", title=title, status="open",
                            assignee=fields["assignee"])
    box = open_inbox("seed", TrackerInbox(Plain(), lambda: []), Plain())
    deliver_notice(box, "lead", "capacity: x", "capacity:x:wu:2026-11-27", frm="st")
    assert created and created[0][0] == "inbox: capacity: x"
