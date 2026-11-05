"""`st crew` reports how much open work is in NOBODY'S haul (aegis-jqcs3).

Hauls feed from READY beads ASSIGNED to a worker, so an unassigned bead is queued
nowhere: it does not self-feed, no stop event advances to it, and it surfaces only
if somebody runs `bd ready` and picks it by hand. Measured 2026-08-05: 114 of 635
open beads had no assignee — a third of the board — including three P1s, while
`st crew` answered free/busy and the fleet twice read as "nothing dispatchable".

The roster answers "who can take this". Without this number it cannot answer the
other half of the same question, "what is not queued anywhere", and a coordinator
reading a green roster has no way to know.

The contract:
  · the count is printed when it is non-zero, with how many are P1-or-above
  · `decision-needed` is excluded using labels on the real WorkItem type;
    fixtures must use the same type rather than adding attributes themselves
  · an unreachable tracker prints `?` and says it is NOT zero — never a bare 0,
    which is the could-not-tell-rendered-as-fine bug in the one number a
    coordinator would use to decide there is nothing to route
  · a clean board prints nothing at all — a line that always appears is noise
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shantytown import cli
from shantytown.protocols import WorkItem


def _item(id_, status="open", assignee=None, priority=2, labels=()):
    return WorkItem(id=id_, title=f"t-{id_}", status=status,
                    assignee=assignee, priority=priority, labels=labels)


def _store(tmp_path: Path) -> Path:
    crew = tmp_path / "crew"; crew.mkdir(parents=True, exist_ok=True)
    (crew / "sattler.json").write_text(json.dumps(
        {"role": "administrator", "pane": "shanty-sattler"}))
    return tmp_path


def _rows(monkeypatch, rows):
    """Point the counter at a fixed item list, bypassing bd entirely.

    Deliberately hands back the rows UNTOUCHED. The earlier version decorated them
    with attributes the real WorkItem does not have, which is how a filter that
    could never fire passed five tests.
    """
    monkeypatch.setattr(cli, "_tracker", lambda a, default="files": object())
    monkeypatch.setattr(cli.beads_mod, "items", lambda _trk: list(rows))


def test_counts_open_beads_with_no_assignee(tmp_path, monkeypatch, capsys):
    _rows(monkeypatch, [
        _item("a-1"), _item("a-2"),
        _item("a-3", assignee="ellie"),
        _item("a-4", status="closed"),
    ])
    n, top, why = cli._unassigned_open(type("A", (), {"root": _store(tmp_path)})())
    assert (n, why) == (2, "")


def test_p1_and_above_are_counted_separately(tmp_path, monkeypatch):
    _rows(monkeypatch, [
        _item("a-1", priority=1), _item("a-2", priority=0), _item("a-3", priority=3),
    ])
    n, top, _ = cli._unassigned_open(type("A", (), {"root": _store(tmp_path)})())
    assert (n, top) == (3, 2), "P0 and P1 both count as 'P1 or above'"


def test_an_unreachable_tracker_is_NOT_zero(tmp_path, monkeypatch):
    """The whole point. A coordinator reading `0 unassigned` concludes there is
    nothing to route; reading `?` goes and looks."""
    def boom(a, default="files"):
        raise RuntimeError("bd list failed: connection refused")
    monkeypatch.setattr(cli, "_tracker", boom)
    n, top, why = cli._unassigned_open(type("A", (), {"root": _store(tmp_path)})())
    assert n is None and top is None
    assert "connection refused" in why


def test_decision_needed_is_excluded_using_real_work_item_labels(tmp_path, monkeypatch):
    _rows(monkeypatch, [
        _item("decision", priority=0, labels=("decision-needed",)),
        _item("work", priority=1),
        _item("other-label", priority=2, labels=("ordinary",)),
    ])
    assert cli._unassigned_open(type("A", (), {"root": _store(tmp_path)})()) == (2, 1, "")


def test_a_clean_board_prints_nothing(tmp_path, monkeypatch):
    """A line that always appears is noise, and noise is how a real number gets
    ignored — the failure this whole bead is about, one layer over."""
    _rows(monkeypatch, [_item("a-1", assignee="ellie")])
    n, _, _ = cli._unassigned_open(type("A", (), {"root": _store(tmp_path)})())
    assert n == 0
