"""Provider refusals hold; fixture replay never reaches a real pane or inbox."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shantytown import cli, safeguard, stop_event, tend, triage
from shantytown.answer import Answer
from shantytown.inbox import FilesInbox
from shantytown.protocols import Agent
from shantytown.runtime import ClaudeRuntime, safeguard_blocked
from shantytown.tmux import NullPanes, PaneNotAgent, Tmux

CAPTURE = (Path(__file__).parent / "fixtures/safeguard-refusal.txt").read_text()
CURRENT = CAPTURE.replace("\n❯ ", "\nRequest ID: req_fixture\n❯ ")
CARD = Agent(name="fixture-worker", role="worker", pane="pane")


@pytest.mark.parametrize("screen", [CURRENT, CURRENT + "\n" * 20,
    CURRENT.replace("❯ ", "❯ suggestion in the composer"),
    CURRENT.replace("safeguards flagged", "safeguards stopped").replace("this message", "the response"),
    CURRENT.replace("safeguards", "\x1b[31msafeguards\x1b[0m")])
def test_current_banner_holds_every_state_and_dispatch(screen):
    panes = NullPanes(screen)
    assert safeguard_blocked(None, triage.strip_attrs(screen))
    assert triage.work_state(screen, True) == tend.SAFEGUARD_BLOCKED
    assert triage.triage(panes, "pane", "new work").action == triage.Action.REFUSE
    with pytest.raises(PaneNotAgent, match="safeguard-blocked"):
        panes.send("pane", "new input")
    assert panes.sent == panes.controls == []


@pytest.mark.parametrize("screen", [
    CURRENT + "\n" + "old output\n" * 50 + "❯ \n? for shortcuts",
    CURRENT + "\n❯ /clear\n❯ next task\n● Working normally\n❯ ",
    CURRENT + "\n● Bash(echo successful)\n  ⎿ successful\n❯ ",
    "quoted: " + CURRENT,
    "● Login expired · Please run /login\n❯ ",
    "You've hit your limit · resets in 1h\n❯ ",
])
def test_historical_cleared_quoted_auth_and_limit_are_not_safeguards(screen):
    assert not safeguard_blocked(None, screen)
    assert triage.work_state(screen, True) != tend.SAFEGUARD_BLOCKED


def test_real_send_guard_refuses_before_typing(monkeypatch):
    panes = Tmux()
    monkeypatch.setattr(panes, "_refuse_in_mode", lambda *a: None)
    monkeypatch.setattr(panes, "foreground", lambda *a: "claude")
    monkeypatch.setattr(panes, "capture", lambda *a, **kw: CURRENT)
    with pytest.raises(PaneNotAgent, match="safeguard-blocked"):
        panes._send("pane", "must not be typed")


def test_actual_tend_and_durable_report_once_without_recovery(tmp_path, monkeypatch):
    panes = NullPanes(CURRENT)
    runtime = ClaudeRuntime(panes, lambda c: None)
    runtime.start = lambda *a: pytest.fail("automatic start/cycle")
    tender = tend.Tender(panes, runtime, None, codex_block=lambda c: None,
                         fallback_model=lambda c: pytest.fail("model switch"))
    rep = tender.pass_over([CARD])
    assert [f.verdict for f in rep.faults] == [tend.SAFEGUARD_BLOCKED]
    assert not rep.acted and not rep.healthy()
    assert "safeguard-blocked" in cli._automatic_cycle_refusal(
        CARD, CARD.pane, panes, runtime, tmp_path, allow_limited=True)
    box = FilesInbox(tmp_path / "inbox")
    class Registry:
        def all(self):
            return Answer.complete_read([CARD, Agent(name="admin", role="administrator")], how="fixture")
    monkeypatch.setattr(cli, "_registry", lambda a: Registry())
    monkeypatch.setattr(cli, "_plate", lambda a: lambda name: [SimpleNamespace(id="fixture-item")])
    monkeypatch.setattr(cli, "_inbox", lambda *a, **kw: box)
    args = SimpleNamespace(root=tmp_path)
    assert cli._safeguard_reports(args, [CARD], rep, panes) == [CARD.name]
    assert cli._safeguard_reports(args, [CARD], rep, panes) == []
    messages = box.unread("admin")
    assert len(messages) == 1
    assert all(x in messages[0].body for x in [CARD.name, "req_fixture", "fixture-item"])
    assert panes.sent == panes.controls == []
    registry = SimpleNamespace(get=lambda name: CARD)
    assert stop_event._liveness(registry, panes, runtime.shows_ready_ui,
                                CARD.name) == tend.SAFEGUARD_BLOCKED


def test_unknown_delivery_is_not_replayed(tmp_path):
    panes = NullPanes(CURRENT)
    findings = [tend.Finding(CARD.name, "up", tend.SAFEGUARD_BLOCKED)]
    attempts, logs = [], []
    def deliver(text):
        attempts.append(text)
        raise TimeoutError("write may have committed")
    with pytest.raises(TimeoutError):
        safeguard.report(tmp_path, findings, [CARD], panes, lambda n: [], deliver, logs.append)
    assert safeguard.report(tmp_path, findings, [CARD], panes, lambda n: [], deliver, logs.append) == []
    assert len(attempts) == 1 and "UNKNOWN" in logs[-1]
    assert json.loads(next((tmp_path / "safeguard-reports").glob("*.json")).read_text())["state"] == "UNKNOWN"


def test_fresh_read_and_unknown_request_plate_are_explicit(tmp_path):
    findings = [tend.Finding(CARD.name, "up", tend.SAFEGUARD_BLOCKED)]
    messages = []
    def unavailable(name):
        raise OSError("plate unavailable")
    assert safeguard.report(tmp_path, findings, [CARD], NullPanes(CAPTURE), unavailable,
                            lambda text: messages.append(text) or "receipt", lambda text: None)
    assert "requests=UNKNOWN" in messages[0] and "plate=UNKNOWN" in messages[0]
    assert not safeguard.report(tmp_path, findings, [CARD], NullPanes("● Healthy now\n❯ "),
                                unavailable, lambda text: pytest.fail("stale report"), lambda text: None)


def test_reservation_failure_never_sends(tmp_path, monkeypatch):
    def unavailable(*args):
        raise OSError("cannot persist reservation")
    monkeypatch.setattr(safeguard, "_save", unavailable)
    with pytest.raises(OSError):
        safeguard.report(tmp_path, [tend.Finding(CARD.name, "up", tend.SAFEGUARD_BLOCKED)],
                         [CARD], NullPanes(CURRENT), lambda name: [],
                         lambda text: pytest.fail("unreserved delivery"), lambda text: None)


def test_unknown_after_delivery_save_does_not_duplicate(tmp_path, monkeypatch):
    save = safeguard._save
    def fail_after_delivery(path, value):
        if value["state"] == "delivered":
            raise OSError("receipt persistence lost")
        save(path, value)
    monkeypatch.setattr(safeguard, "_save", fail_after_delivery)
    attempts, logs = [], []
    findings = [tend.Finding(CARD.name, "up", tend.SAFEGUARD_BLOCKED)]
    with pytest.raises(OSError):
        safeguard.report(tmp_path, findings, [CARD], NullPanes(CURRENT), lambda name: [],
                         lambda text: attempts.append(text) or "durable-id", logs.append)
    assert safeguard.report(tmp_path, findings, [CARD], NullPanes(CURRENT), lambda name: [],
                            lambda text: pytest.fail("duplicate delivery"), logs.append) == []
    assert len(attempts) == 1 and "UNKNOWN" in logs[-1]


def test_unknown_id_moving_footer_does_not_repeat_report(tmp_path):
    messages = []
    findings = [tend.Finding(CARD.name, "up", tend.SAFEGUARD_BLOCKED)]
    deliver = lambda text: messages.append(text) or "durable-id"
    assert safeguard.report(tmp_path, findings, [CARD], NullPanes(CAPTURE),
                            lambda name: [], deliver, lambda text: None)
    assert safeguard.report(tmp_path, findings, [CARD], NullPanes(CAPTURE + "\nupdated footer"),
                            lambda name: [], deliver, lambda text: None) == []
    assert len(messages) == 1
