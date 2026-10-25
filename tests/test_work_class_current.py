"""Current governed Codex-only routing through the normal admission path."""
from types import SimpleNamespace as NS

import pytest

from shantytown import cli, governor as gov, work_class
from shantytown.protocols import Agent
from test_work_class import world, put


@pytest.mark.parametrize("labels", [
    ["work:design"], ["work:important-quipu-code"], [], ["work:review"],
])
@pytest.mark.parametrize("target", ["coder", "writer"])
def test_current_rule_normal_dispatch_is_codex_only(tmp_path, monkeypatch, labels, target):
    _, tracker, panes = world(tmp_path, monkeypatch)
    put(tracker, labels)
    before = tracker._path("job").read_bytes()
    result = cli.main(["--root", str(tmp_path), "--backend", "files",
                       "go", "job", target, "--dry-run"])
    assert (result == 0) is (target == "coder")
    assert tracker._path("job").read_bytes() == before
    assert not panes.sent


@pytest.mark.parametrize("role", ["lead", "keeper", "worker", "administrator"])
def test_current_rule_only_configured_actual_administrator_has_claude_allowance(role):
    policy = gov.Policy(admit_class=True, class_exempt=("chief",))
    card = Agent("chief", role=role, harness="claude")
    verdict = work_class.for_card(gov.Verdict(reading=gov.Reading(source="none")), policy, card)
    refusal = verdict.admits(NS(id="job", priority=1, labels=["work:design"]), "chief")
    assert bool(refusal) is (role != "administrator")
    if role == "administrator":
        from dataclasses import replace
        assert replace(verdict, frozen=True).admits(NS(id="job", priority=0), "chief")


@pytest.mark.parametrize("guard", ["plate", "hold"])
def test_important_codex_admission_keeps_normal_capacity_and_operator_holds(tmp_path, monkeypatch, guard):
    _, tracker, panes = world(tmp_path, monkeypatch)
    put(tracker, ["work:important-quipu-code"])
    if guard == "plate":
        for index in range(10):
            tracker.create(f"Retained {index}", assignee="coder")
    else:
        from shantytown import agent_hold
        agent_hold.hold(tmp_path, "coder", "operator", "private control")
    before = tracker._path("job").read_bytes()
    assert cli.main(["--root", str(tmp_path), "--backend", "files",
                     "go", "job", "coder", "--dry-run"]) == cli.REFUSED
    assert tracker._path("job").read_bytes() == before
    assert not panes.sent
