"""The defer writer's real output must reach the mechanical sweeper (aegis-tdf)."""
import json
from datetime import datetime, timezone

import pytest

from shantytown import resume_kinds
from shantytown.dispatch import Dispatcher
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.notify import DeferralAlerter
from shantytown.tmux import NullPanes


class World:
    def __init__(self, root, prose="", old_notes=None, *, condition="closed:blocker", kind="bead"):
        self.tracker = FilesTracker(root / "items")
        self.registry = FilesRegistry(root / "crew")
        self.panes = NullPanes()
        for ident in ("waiter", "blocker"):
            self.tracker.update(ident, title="private resume fixture", status="open", priority=2)
        if old_notes:
            self.tracker.update("waiter", notes=old_notes)
        reason = (prose + "\n" if prose else "") + "resume_when: " + condition
        Dispatcher(self.registry, self.tracker, self.panes).defer(
            "waiter", kind, reason,
            dependency_reason="Requires completed fixture blocker" if condition.startswith("closed:") else "")
        self.tracker.update("blocker", status="closed")
        self.released = []
        self.root = root

    def row(self, ident="waiter"):
        # The file adapter derives the ID from the filename, not its JSON body.
        return dict(json.loads(self.tracker._path(ident).read_text()), id=ident)

    def sweep(self, fresh=None, closed_read=None):
        snapshot = self.row()

        def show(ident):
            row = self.row(ident)
            return fresh(row) if fresh and ident == "waiter" else row

        def release(ident):
            self.released.append(ident)
            self.tracker.update(ident, status="open", defer_until=None, blocker_kind="")

        DeferralAlerter(
            self.root, self.registry, self.panes, read=lambda: [snapshot],
            show=show, is_closed=closed_read or (lambda ident: self.tracker.get(ident).status == "closed"),
            release=release, now=lambda: datetime.now(timezone.utc),
            push=lambda *_: None).sweep()


def test_marker_only_writer_output_resumes_once_when_condition_is_met(tmp_path):
    w = World(tmp_path)
    assert "dependency_reason:" in w.row()["notes"]
    assert "gate_scope_flag:" in w.row()["notes"]
    w.sweep()
    assert w.released == ["waiter"]
    assert w.row()["status"] == "open" and not w.row().get("defer_until")
    w.sweep()
    assert w.released == ["waiter"]


@pytest.mark.parametrize("prose", ["Needs Stiwi sign-off", "Waiting for review."])
def test_reason_prose_is_still_a_judgement_gate(tmp_path, prose):
    w = World(tmp_path, prose)
    w.sweep()
    assert not w.released and w.row()["status"] == "deferred"


@pytest.mark.parametrize("label", ["blocked:human", "blocked:access", "needs-human", "parked:by-design"])
def test_other_blocker_labels_still_hold(tmp_path, label):
    w = World(tmp_path)
    w.tracker.update("waiter", labels=w.row()["labels"] + [label])
    w.sweep()
    assert not w.released


@pytest.mark.parametrize("answer", [False, None])
def test_unmet_and_unknown_closure_reads_stay_held(tmp_path, answer):
    w = World(tmp_path)
    w.sweep(closed_read=lambda _: answer)
    assert not w.released


@pytest.mark.parametrize("suffix", [
    "\nNeeds Stiwi sign-off",
    "\nresume_when: closed:another-blocker",
    "\ngate_scope_flag: human approval still required",
    "\nunknown_field: pending",
])
def test_extra_notes_are_not_discarded_as_generated_metadata(tmp_path, suffix):
    w = World(tmp_path)
    w.tracker.update("waiter", notes=w.row()["notes"] + suffix)
    w.sweep()
    assert not w.released


@pytest.mark.parametrize("envelope", [
    'defer_provenance: not-json',
    'defer_provenance: {"actor":"worker","set_at":"bad","until":""}',
    'defer_provenance: {"actor":"worker","set_at":"2026-01-01T00:00:00Z","until":"","approval":"needed"}',
    'defer_provenance: {"actor":"worker","set_at":"2026-01-01T00:00:00Z","until":"bad"}',
    'defer_provenance: {"until": "", "set_at": "2026-01-01T00:00:00Z", "actor": "worker"}',
])
def test_malformed_or_extended_provenance_is_not_discarded(tmp_path, envelope):
    w = World(tmp_path)
    notes = w.row()["notes"].splitlines()
    assert notes[-1].startswith("defer_provenance: ")
    w.tracker.update("waiter", notes="\n".join(notes[:-1] + [envelope]))
    w.sweep()
    assert not w.released


def test_duplicate_provenance_envelopes_are_not_discarded(tmp_path):
    w = World(tmp_path)
    notes = w.row()["notes"]
    w.tracker.update("waiter", notes=notes + "\n" + notes.splitlines()[-1])
    w.sweep()
    assert not w.released


def test_historical_prose_is_not_erased_by_a_new_closed_marker(tmp_path):
    w = World(tmp_path, old_notes="Needs Stiwi sign-off")
    w.sweep()
    assert not w.released


def test_fresh_read_finds_new_prose_before_mutation(tmp_path):
    w = World(tmp_path)
    w.sweep(fresh=lambda row: dict(row, notes=row["notes"] + "\nNeeds Stiwi sign-off"))
    assert not w.released


MECHANICAL = ["closed:blocker", "release:example/project@v1.0.0", "installed:sd@0.6.7"]


@pytest.mark.parametrize("condition", MECHANICAL)
@pytest.mark.parametrize("answer", [True, False, None])
def test_external_kind_requires_a_definite_met_mechanical_condition(tmp_path, monkeypatch, condition, answer):
    w = World(tmp_path, condition=condition, kind="external")
    monkeypatch.setattr(resume_kinds, "evaluate", lambda *_: (answer, "private fact read"))
    w.sweep(closed_read=lambda _: answer)
    assert w.released == (["waiter"] if answer is True else [])


@pytest.mark.parametrize("condition", MECHANICAL)
@pytest.mark.parametrize("label", ["blocked:human", "blocked:access"])
def test_met_external_condition_never_clears_human_or_access_holds(tmp_path, monkeypatch, condition, label):
    w = World(tmp_path, condition=condition, kind="external")
    w.tracker.update("waiter", labels=w.row()["labels"] + [label])
    monkeypatch.setattr(resume_kinds, "evaluate", lambda *_: (True, "private fact met"))
    w.sweep()
    assert not w.released


@pytest.mark.parametrize("condition", MECHANICAL)
def test_met_external_condition_never_discards_prose(tmp_path, monkeypatch, condition):
    w = World(tmp_path, "Needs Stiwi sign-off", condition=condition, kind="external")
    monkeypatch.setattr(resume_kinds, "evaluate", lambda *_: (True, "private fact met"))
    w.sweep()
    assert not w.released


def test_external_date_review_is_not_automatic_permission(tmp_path):
    w = World(tmp_path, condition="date:2020-01-01", kind="external")
    w.sweep()
    assert not w.released
