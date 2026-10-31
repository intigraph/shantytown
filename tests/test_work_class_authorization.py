"""Authoring needs no exception; exact review labels still constrain admission."""
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from shantytown import cli, feed_check, governor as gov, work_class
from test_work_class import put, world


@pytest.mark.parametrize("labels,allowed", [
    (["work:design", "work:claude-authorized"], True),
    (["work:important-quipu-code", "work:claude-authorized"], True),
    (["work:design"], True),
    (["work:claude-authorized"], True),
    (["work:docs", "work:claude-authorized"], True),
    (["work:important-code", "work:claude-authorized"], True),
    (["work:design", "work:claude-authorized", "work:review"], False),
    (None, False), ("work:design", False),
    ([None, "work:design", "work:claude-authorized"], False),
])
def test_authoring_needs_readable_class_but_no_authorization_label(labels, allowed):
    item = NS(id="task", labels=labels)
    assert (not work_class.lane_refusal(item, "claude", "author")) is allowed
    assert not work_class.lane_refusal(item, "codex", "coder")
    assert work_class.lane_refusal(item, "unknown", "unknown")


@pytest.mark.parametrize("kind", ["work:design", "work:important-quipu-code"])
def test_normal_dispatch_removes_legacy_authorization_without_revoking_authoring(tmp_path, monkeypatch, kind):
    _, tracker, panes = world(tmp_path, monkeypatch)
    put(tracker, [kind, "work:claude-authorized"])
    tracker.update("job", priority=0)
    args = ["--root", str(tmp_path), "--backend", "files", "go", "job", "writer", "--dry-run"]
    before = tracker._path("job").read_bytes()
    assert cli.main(args) == 0
    assert tracker._path("job").read_bytes() == before
    tracker.update("job", labels=[kind])
    assert cli.main(args) == 0
    assert not panes.sent


def test_authorized_private_dispatch_assigns_only_explicit_target(tmp_path, monkeypatch):
    _, tracker, panes = world(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "_graph_context", lambda *a: (
        NS(render=lambda: "private graph fixture", nodes=("fixture",)), None))
    put(tracker, ["work:design", "work:claude-authorized"])
    tracker.update("job", priority=0)
    assert cli.main(["--root", str(tmp_path), "--backend", "files", "go", "job", "writer"]) == 0
    assert tracker.get("job").assignee == "writer"
    assert len(panes.sent) == 1


def test_feed_and_haul_reread_authorization_instead_of_ready_snapshot(tmp_path, monkeypatch):
    reg, tracker, panes = world(tmp_path, monkeypatch)
    forged = NS(id="job", priority=0, labels=["work:design", "work:claude-authorized"])
    put(tracker, ["work:review", "work:design"])
    checks = feed_check.worker_governor_admissions(tmp_path, reg, ["writer", "coder"])
    assert checks["writer"](forged)
    tracker.update("job", labels=["work:design", "work:claude-authorized"])
    checks = feed_check.worker_governor_admissions(tmp_path, reg, ["writer", "coder"])
    assert not checks["writer"](forged)
    tracker.update("job", labels=["work:review", "work:design"])
    checks = feed_check.worker_governor_admissions(tmp_path, reg, ["writer", "coder"])
    assert checks["writer"](forged)
    assert checks["writer"](NS(id="missing", priority=0, labels=forged.labels))
    assert not checks["coder"](forged)
    card = reg.get("writer")
    verdict = work_class.for_card(gov.Verdict(reading=gov.Reading(source="none")),
                                  gov.Policy(admit_class=True), card, tmp_path)
    assert not feed_check.admitted_haul([vars(forged)], card, verdict, lambda _: None, root=tmp_path)
    tracker.update("job", labels=forged.labels)
    assert len(feed_check.admitted_haul([vars(forged)], card, verdict, lambda _: None, root=tmp_path)) == 1
    assert not panes.sent


@pytest.mark.parametrize("restriction", ["floor", "freeze", "drain"])
def test_task_authorization_cannot_waive_governor_restrictions(restriction):
    verdict = gov.Verdict(reading=gov.Reading(source="none"), admit_class=True, work_harness="claude")
    item = NS(id="task", priority=1, labels=["work:design", "work:claude-authorized"])
    assert not verdict.admits(item, "author")
    if restriction == "freeze":
        verdict = replace(verdict, frozen=True)
    else:
        tier = gov.Tier(at=50, min_priority=0) if restriction == "floor" else gov.Tier(at=90, action="drain")
        verdict = replace(verdict, tier=tier, engaged=(tier,))
    assert verdict.admits(item, "author")


@pytest.mark.parametrize("restriction", ["plate", "hold"])
def test_authorized_claude_keeps_dispatch_holds(tmp_path, monkeypatch, restriction):
    _, tracker, panes = world(tmp_path, monkeypatch)
    put(tracker, ["work:design", "work:claude-authorized"])
    if restriction == "plate":
        for index in range(10):
            tracker.create(f"Retained {index}", assignee="writer")
    else:
        from shantytown import agent_hold
        agent_hold.hold(tmp_path, "writer", "operator", "private control")
    before = tracker._path("job").read_bytes()
    assert cli.main(["--root", str(tmp_path), "--backend", "files", "go", "job", "writer", "--dry-run"]) == cli.REFUSED
    assert tracker._path("job").read_bytes() == before
    assert not panes.sent
