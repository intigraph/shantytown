"""Regression coverage for the re-dispatch leg of ``st agent cycle`` (aegis-wjnf3)."""
from __future__ import annotations

import json
from argparse import Namespace

import shantytown.cli as cli
from shantytown.dispatch import Dispatcher
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.tmux import NullPanes


def test_empty_or_failed_plate_submits_resume_prompt(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    panes = NullPanes(screen="❯ ")
    monkeypatch.setattr(cli, "_panes", lambda a: panes)
    monkeypatch.setattr(cli, "_registry", lambda a: SimpleNamespace(
        get=lambda who: SimpleNamespace(pane="private-worker", name=who)))
    monkeypatch.setattr(cli, "_tracker", lambda a: object())
    args = Namespace(root=tmp_path)
    for failed in (False, True):
        def read(*args, **kwargs):
            if failed:
                raise RuntimeError("HTTP 408")
            return None
        monkeypatch.setattr(cli, "_tracker_plate", read)
        cli._redispatch_after_cycle(args, "worker", "x-checkpoint")
        assert "st anchor worker" in panes.sent[-1][1]
        assert "x-checkpoint" in panes.sent[-1][1]
        assert "resume" in panes.sent[-1][1]
    assert len(panes.sent) == 2
    output = capsys.readouterr()
    assert "plate UNKNOWN" in output.err
    assert "HTTP 408" in output.err


def test_complete_cycle_plate_rejects_failed_listing(monkeypatch):
    import pytest
    from shantytown.br import BrTracker
    tracker = BrTracker()
    monkeypatch.setattr(tracker, "plate_rows", lambda who: (_ for _ in ()).throw(
        RuntimeError("HTTP 408")), raising=False)
    with pytest.raises(RuntimeError, match="408"):
        cli._tracker_plate(tracker, "worker", require_complete=True)


def test_delivered_but_untracked_cycle_does_not_send_twice(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from shantytown.dispatch import DispatchedButUntracked
    monkeypatch.setattr(cli, "_tracker", lambda a: object())
    monkeypatch.setattr(cli, "_tracker_plate", lambda *a, **kw: SimpleNamespace(id="x-1"))
    def go(*a, **kw):
        raise DispatchedButUntracked("x-1", "worker", "p", RuntimeError("408"))
    monkeypatch.setattr(cli, "_wire", lambda a: SimpleNamespace(go=go))
    def forbidden(*a):
        raise AssertionError("a delivered turn must not receive a second kickoff")
    monkeypatch.setattr(cli, "_kickoff_after_cycle", forbidden)
    cli._redispatch_after_cycle(Namespace(root=tmp_path), "worker")


def test_resume_kickoff_respects_busy_pane_and_reports_unverified_send(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    monkeypatch.setattr(cli, "_registry", lambda a: SimpleNamespace(
        get=lambda who: SimpleNamespace(pane="p")))
    for panes in (NullPanes(screen="❯ \nRunning…"),
                  NullPanes(screen="[st cycle resume] [resume-id:old]\n❯ ", drops=True)):
        monkeypatch.setattr(cli, "_panes", lambda a: panes)
        cli._kickoff_after_cycle(Namespace(root=tmp_path), "worker", "")
        assert "NOT CONFIRMED" in capsys.readouterr().err
    assert len(panes.sent) == 1, "dropped submission is attempted once, never blind retried"


def test_cycle_redispatch_writes_the_item_assignment(tmp_path, monkeypatch):
    """A successful return is insufficient: the item must actually be reassigned.

    The live failure called a nonexistent ``_dispatcher`` factory, swallowed the
    NameError into a note, and returned success after clearing the agent. Pin the
    tracker state so that success-shaped non-delivery cannot regress unnoticed.
    """
    root = tmp_path / ".shanty"
    (root / "crew").mkdir(parents=True)
    (root / "crew" / "malcolm.json").write_text(json.dumps({
        "role": "worker", "pane": "shanty-malcolm",
    }))
    (root / "items").mkdir()
    item_path = root / "items" / "aegis-fbrr0.json"
    item_path.write_text(json.dumps({
        "title": "standing list", "status": "open", "assignee": "malcolm",
    }))

    tracker = FilesTracker(root / "items")
    panes = NullPanes(screen="")
    dispatcher = Dispatcher(FilesRegistry(root / "crew"), tracker, panes)
    args = Namespace(root=root, backend="files", repo=None)

    # The production beads backend supplies its own plate reader. Inject the
    # equivalent files-backend read while retaining the real tracker + dispatch.
    monkeypatch.setattr(cli.beads_mod, "plate",
                        lambda _tracker, _agent: tracker.get("aegis-fbrr0"))
    monkeypatch.setattr(cli, "_wire", lambda _args: dispatcher)

    cli._redispatch_after_cycle(args, "malcolm", "aegis-checkpoint")

    written = json.loads(item_path.read_text())
    assert written["status"] == "in_progress"
    assert written["assignee"] == "malcolm"
    assert len(panes.sent) == 1
    assert "aegis-fbrr0" in panes.sent[0][1]
