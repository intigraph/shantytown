"""Real notification/store seams in a private root; no live provider or pane."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shantytown import cli, runtime, safeguard, stop_failure, tend
from shantytown.events import FilesEvents
from shantytown.files import FilesRegistry
from shantytown.inbox import FilesInbox
from shantytown.launched import FilesLaunches
from shantytown.protocols import Agent
from shantytown.tmux import Tmux, PaneNotAgent, NullPanes

CARD = Agent(name="fixture-worker", role="worker", pane="fixture-pane")
PAYLOAD = {"error": "unknown", "session_id": "fixture-session",
           "error_details": "fixture provider error",
           "last_assistant_message": "API Error: safeguards stopped the response. Request ID: req_fixture"}


def setup_root(root):
    registry = FilesRegistry(root / "crew")
    registry.set(CARD)
    settings = root / "settings.json"
    settings.write_text(json.dumps(runtime.claude_settings_for_role("worker", root)))
    FilesLaunches(root / "launched").record(CARD.name, settings)
    return settings


@pytest.mark.parametrize("payload,expected", [
    (PAYLOAD, "safeguard-blocked"),
    ({**PAYLOAD, "error": "rate_limit"}, "safeguard-blocked"),
    ({"error": "rate_limit"}, "limited"),
    ({"error": "authentication_failed"}, "auth-dead"),
    ({"error": "billing_error"}, "stop-failure"),
    ({"error": "future-value"}, "stop-failure"),
])
def test_error_routes(payload, expected):
    assert stop_failure.classify(payload) == expected


def test_real_hook_payload_event_inbox_and_fallback_dedup(tmp_path):
    setup_root(tmp_path)
    events, inbox = FilesEvents(tmp_path / "events"), FilesInbox(tmp_path / "inbox")
    def deliver(text):
        assert stop_failure.state(tmp_path, CARD.name) == "safeguard-blocked"
        assert events.pending("admin")
        return inbox.deliver("admin", text, frm="st-stop-failure").id
    for _ in range(2):
        stop_failure.capture(tmp_path, CARD.name, PAYLOAD, administrator="admin", events=events,
                             plate=lambda name: ("fixture-item", "in_progress"), deliver=deliver)
    pending = events.pending("admin")
    assert len(pending) == len(inbox.unread("admin")) == 1
    assert pending[0].reason == "stop-failure"
    detail = json.loads(pending[0].detail)
    assert detail["kind"] == "stop-failure"
    assert all(detail[k] == v for k, v in PAYLOAD.items())
    assert pending[0].item == "fixture-item"
    text = inbox.unread("admin")[0].body
    assert all(x in text for x in ("req_fixture", CARD.name, "fixture-item", "safeguard-blocked"))
    screen = "● API Error: safeguards stopped the response\nreq_fixture\n❯ "
    findings = [tend.Finding(CARD.name, "up", tend.SAFEGUARD_BLOCKED)]
    assert safeguard.report(tmp_path, findings, [CARD], NullPanes(screen), lambda n: [], deliver, print) == []
    assert len(inbox.unread("admin")) == 1


def test_primary_holds_without_banner_and_relaunch_retires(tmp_path, monkeypatch):
    settings = setup_root(tmp_path)
    stop_failure.capture(tmp_path, CARD.name, PAYLOAD, administrator="admin",
                         events=FilesEvents(tmp_path / "events"), plate=lambda n: (None, "?"), deliver=lambda t: "receipt")
    assert stop_failure.pane_state(tmp_path, CARD.pane) == "safeguard-blocked"
    panes = Tmux(root=tmp_path)
    monkeypatch.setattr(panes, "_refuse_in_mode", lambda *a: None)
    monkeypatch.setattr(panes, "foreground", lambda *a: "claude")
    monkeypatch.setattr(panes, "capture", lambda *a, **kw: "❯ ")
    with pytest.raises(PaneNotAgent, match="safeguard-blocked"):
        panes._send(CARD.pane, "must not send")
    private = NullPanes("❯ ")
    rt = runtime.ClaudeRuntime(private, lambda card: settings, root=tmp_path)
    rt.start = lambda *a: pytest.fail("auto-cycle")
    rep = tend.Tender(private, rt, None, codex_block=lambda c: None).pass_over([CARD])
    assert [f.verdict for f in rep.faults] == ["safeguard-blocked"]
    assert not rep.acted
    assert "safeguard-blocked" in cli._automatic_cycle_refusal(CARD, CARD.pane, private, rt, tmp_path)
    stop_failure.clear_recovered(tmp_path, CARD.name)
    assert stop_failure.state(tmp_path, CARD.name) == "safeguard-blocked"
    # Human launch gets a fresh stamp; no automated launch was invoked.
    FilesLaunches(tmp_path / "launched").record(CARD.name, settings)
    assert not stop_failure.state(tmp_path, CARD.name)


def test_unknown_delivery_reserved_and_never_retried(tmp_path):
    setup_root(tmp_path)
    calls = []
    def fail(text):
        calls.append(text)
        raise TimeoutError("may have committed")
    args = dict(administrator="admin", events=FilesEvents(tmp_path / "events"), plate=lambda n: (None, "?"), deliver=fail)
    with pytest.raises(TimeoutError):
        stop_failure.capture(tmp_path, CARD.name, PAYLOAD, **args)
    stop_failure.capture(tmp_path, CARD.name, PAYLOAD, **args)
    assert len(calls) == 1
    assert stop_failure.state(tmp_path, CARD.name) == "safeguard-blocked"


@pytest.mark.parametrize("error,verdict", [("rate_limit", "limited"), ("authentication_failed", "auth-dead")])
def test_limit_auth_no_generic_inbox_and_success_can_retire(tmp_path, error, verdict):
    setup_root(tmp_path)
    events = FilesEvents(tmp_path / "events")
    stop_failure.capture(tmp_path, CARD.name, {"error": error}, administrator="admin", events=events,
                         plate=lambda n: (None, None), deliver=lambda t: pytest.fail("generic routing"))
    assert stop_failure.state(tmp_path, CARD.name) == verdict
    stop_failure.clear_recovered(tmp_path, CARD.name)
    assert not stop_failure.state(tmp_path, CARD.name)
    assert len(events.pending("admin")) == 1


def test_provisioned_async_hook_and_live_snapshot(tmp_path):
    settings = setup_root(tmp_path)
    read = lambda pane: f"claude --settings {settings}"
    assert stop_failure.verify_wiring(tmp_path, CARD.name, CARD.pane, read) == "verified"
    # Updating the file cannot change the bytes the running process loaded.
    original = json.loads(settings.read_text())
    original["hooks"].pop("StopFailure")
    settings.write_text(json.dumps(original))
    assert stop_failure.verify_wiring(tmp_path, CARD.name, CARD.pane, read) == "verified"
    FilesLaunches(tmp_path / "launched").record(CARD.name, settings)
    assert stop_failure.verify_wiring(tmp_path, CARD.name, CARD.pane, read) == "missing"
    assert stop_failure.verify_wiring(tmp_path, CARD.name, CARD.pane, lambda p: None) == "unknown"
    assert stop_failure.verify_wiring(tmp_path, CARD.name, CARD.pane, lambda p: "claude") == "missing"


def test_main_reads_hook_stdin_with_existing_identity_and_backend(tmp_path, monkeypatch, capsys):
    import io
    from shantytown import stop_event
    setup_root(tmp_path)
    registry = FilesRegistry(tmp_path / "crew")
    registry.set(Agent(name="admin", role="administrator"))
    box = FilesInbox(tmp_path / "inbox")
    monkeypatch.setenv("SHANTY_AGENT", CARD.name)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(stop_failure.sys, "stdin", io.StringIO(json.dumps(
        {**PAYLOAD, "hook_event_name": "StopFailure"})))
    monkeypatch.setattr(cli, "_inbox", lambda *a, **kw: box)
    monkeypatch.setattr(stop_event, "_plate_of", lambda root, name: ("fixture-item", "in_progress", []))
    assert stop_failure.main(["--root", str(tmp_path)]) == 0
    assert len(box.unread("admin")) == 1
    assert len(FilesEvents(tmp_path / "events").pending("admin")) == 1
    assert capsys.readouterr().out == ""  # no continuation or block output


@pytest.mark.parametrize("raw", ["not-json", '[]', '{"hook_event_name":"Stop"}',
    '{"hook_event_name":"StopFailure","error_details":{}}', "x" * 65537])
def test_invalid_payload_never_sends_or_blocks(tmp_path, monkeypatch, capsys, raw):
    import io
    monkeypatch.setattr(stop_failure.sys, "stdin", io.StringIO(raw))
    monkeypatch.setattr(cli, "_inbox", lambda *a, **kw: pytest.fail("invalid payload delivered"))
    assert stop_failure.main(["--root", str(tmp_path)]) == 0
    assert "UNKNOWN" in capsys.readouterr().err
    assert not (tmp_path / "events").exists()


def test_new_generic_error_cannot_clear_safety_hold(tmp_path):
    setup_root(tmp_path)
    args = dict(administrator="admin", events=FilesEvents(tmp_path / "events"),
                plate=lambda n: (None, None), deliver=lambda t: "receipt")
    stop_failure.capture(tmp_path, CARD.name, PAYLOAD, **args)
    stop_failure.capture(tmp_path, CARD.name, {"error": "rate_limit"}, **args)
    assert stop_failure.state(tmp_path, CARD.name) == "safeguard-blocked"


def test_generic_failure_is_durable_with_unknown_request_and_plate(tmp_path):
    setup_root(tmp_path)
    inbox = FilesInbox(tmp_path / "inbox")
    stop_failure.capture(tmp_path, CARD.name, {"error": "server_error"}, administrator="admin",
                         events=FilesEvents(tmp_path / "events"), plate=lambda n: (None, "?"),
                         deliver=lambda t: inbox.deliver("admin", t).id)
    assert "requests=UNKNOWN" in inbox.unread("admin")[0].body
    assert "plate=UNKNOWN" in inbox.unread("admin")[0].body


def test_message_with_maximum_ids_stays_inside_durable_byte_cap(tmp_path):
    setup_root(tmp_path)
    text = []
    payload = {**PAYLOAD, "last_assistant_message": "safeguards req_" + "x" * 96 + " req_" + "y" * 96}
    stop_failure.capture(tmp_path, CARD.name, payload, administrator="admin",
                         events=FilesEvents(tmp_path / "events"), plate=lambda n: ("é" * 100, "?"),
                         deliver=lambda t: text.append(t) or "receipt")
    assert len(text[0].encode()) <= 482


def test_primary_hold_covers_down_pane_crew_and_stop_liveness(tmp_path):
    from shantytown import stop_event
    setup_root(tmp_path)
    stop_failure.capture(tmp_path, CARD.name, PAYLOAD, administrator="admin",
                         events=FilesEvents(tmp_path / "events"), plate=lambda n: (None, None), deliver=lambda t: "receipt")
    pane = NullPanes("❯ ")
    pane.delivery_root = tmp_path
    rt = runtime.ClaudeRuntime(pane, lambda c: None, root=tmp_path)
    assert list(cli._crew_states([CARD], pane, rt))[0][2] == "safeguard-blocked"
    assert stop_event._liveness(FilesRegistry(tmp_path / "crew"), pane, rt.shows_ready_ui, CARD.name) == "safeguard-blocked"
    pane.exists = lambda p: False
    tender = tend.Tender(pane, rt, None, codex_block=lambda c: None,
                         spawn=lambda *a: pytest.fail("respawn after refusal"))
    rep = tender.pass_over([CARD])
    assert rep.findings[0].verdict == "safeguard-blocked" and not rep.acted


def test_launch_verification_requires_failure_hook_even_for_isolated_claude(tmp_path, monkeypatch):
    settings = setup_root(tmp_path)
    pane = NullPanes("❯ ")
    pane.cmdline = lambda p: f"claude --settings {settings}"
    rt = runtime.ClaudeRuntime(pane, lambda c: settings, root=tmp_path)
    args = SimpleNamespace(root=tmp_path)
    monkeypatch.setattr(cli, "_registry", lambda a: FilesRegistry(tmp_path / "crew"))
    assert cli._verify_live_hooks(args, CARD, rt, pane, CARD.pane) == cli.OK
    emitted = json.loads(settings.read_text())
    assert emitted["hooks"]["Stop"]
    emitted["hooks"].pop("StopFailure")
    settings.write_text(json.dumps(emitted))
    FilesLaunches(tmp_path / "launched").record(CARD.name, settings)
    assert cli._verify_live_hooks(args, CARD, rt, pane, CARD.pane) == cli.REFUSED


def test_slow_read_cannot_silence_durable_error_notice(tmp_path, monkeypatch):
    import threading
    setup_root(tmp_path)
    gate = threading.Event()
    monkeypatch.setattr(stop_failure, "PLATE_TIMEOUT", 0.01)
    box, events = FilesInbox(tmp_path / "inbox"), FilesEvents(tmp_path / "events")
    def slow(name):
        gate.wait()
        return "late-item", "in_progress"
    try:
        stop_failure.capture(tmp_path, CARD.name, PAYLOAD, administrator="admin", events=events,
                             plate=slow, deliver=lambda text: box.deliver("admin", text).id)
        assert len(box.unread("admin")) == len(events.pending("admin")) == 1
        assert "plate=UNKNOWN" in box.unread("admin")[0].body
        assert events.pending("admin")[0].item_status == "?"
    finally:
        gate.set()
