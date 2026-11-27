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
        stop_failure.capture(tmp_path, CARD.name, PAYLOAD, to="admin", events=events,
                             plate=lambda name: ("fixture-item", "in_progress"), deliver=deliver)
    pending = events.pending("admin")
    assert len(pending) == len(inbox.unread("admin")) == 1
    assert pending[0].kind == pending[0].reason == "stop-failure"
    assert pending[0].error == PAYLOAD["error"]
    assert pending[0].error_details == PAYLOAD["error_details"]
    assert pending[0].last_assistant_message == PAYLOAD["last_assistant_message"]
    persisted = json.loads(next((tmp_path / "events").glob("ev-*.json")).read_text())
    assert persisted["kind"] == "stop-failure"
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
    stop_failure.capture(tmp_path, CARD.name, PAYLOAD, to="admin",
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
    args = dict(to="admin", events=FilesEvents(tmp_path / "events"), plate=lambda n: (None, "?"), deliver=fail)
    with pytest.raises(TimeoutError):
        stop_failure.capture(tmp_path, CARD.name, PAYLOAD, **args)
    stop_failure.capture(tmp_path, CARD.name, PAYLOAD, **args)
    assert len(calls) == 1
    assert stop_failure.state(tmp_path, CARD.name) == "safeguard-blocked"


@pytest.mark.parametrize("error,verdict", [("rate_limit", "limited"), ("authentication_failed", "auth-dead")])
def test_limit_auth_no_generic_inbox_and_success_can_retire(tmp_path, error, verdict):
    setup_root(tmp_path)
    events = FilesEvents(tmp_path / "events")
    stop_failure.capture(tmp_path, CARD.name, {"error": error}, to="admin", events=events,
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


@pytest.mark.parametrize("optional", [{}, {"error_details": None, "session_id": None}])
def test_main_reads_hook_stdin_with_existing_identity_and_backend(tmp_path, monkeypatch, capsys, optional):
    import io
    from shantytown import stop_event
    setup_root(tmp_path)
    registry = FilesRegistry(tmp_path / "crew")
    registry.set(Agent(name="admin", role="administrator"))
    box = FilesInbox(tmp_path / "inbox")
    monkeypatch.setenv("SHANTY_AGENT", CARD.name)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(stop_failure.sys, "stdin", io.StringIO(json.dumps(
        {**PAYLOAD, **optional, "hook_event_name": "StopFailure"})))
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
    args = dict(to="admin", events=FilesEvents(tmp_path / "events"),
                plate=lambda n: (None, None), deliver=lambda t: "receipt")
    stop_failure.capture(tmp_path, CARD.name, PAYLOAD, **args)
    stop_failure.capture(tmp_path, CARD.name, {"error": "rate_limit"}, **args)
    assert stop_failure.state(tmp_path, CARD.name) == "safeguard-blocked"


def test_generic_failure_is_durable_with_unknown_request_and_plate(tmp_path):
    setup_root(tmp_path)
    inbox = FilesInbox(tmp_path / "inbox")
    stop_failure.capture(tmp_path, CARD.name, {"error": "server_error"}, to="admin",
                         events=FilesEvents(tmp_path / "events"), plate=lambda n: (None, "?"),
                         deliver=lambda t: inbox.deliver("admin", t).id)
    assert "requests=UNKNOWN" in inbox.unread("admin")[0].body
    assert "plate=UNKNOWN" in inbox.unread("admin")[0].body


def test_message_with_maximum_ids_stays_inside_durable_byte_cap(tmp_path):
    setup_root(tmp_path)
    text = []
    payload = {**PAYLOAD, "last_assistant_message": "safeguards req_" + "x" * 96 + " req_" + "y" * 96}
    stop_failure.capture(tmp_path, CARD.name, payload, to="admin",
                         events=FilesEvents(tmp_path / "events"), plate=lambda n: ("é" * 100, "?"),
                         deliver=lambda t: text.append(t) or "receipt")
    assert len(text[0].encode()) <= 482


def test_primary_hold_covers_down_pane_crew_and_stop_liveness(tmp_path):
    from shantytown import stop_event
    setup_root(tmp_path)
    stop_failure.capture(tmp_path, CARD.name, PAYLOAD, to="admin",
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
        stop_failure.capture(tmp_path, CARD.name, PAYLOAD, to="admin", events=events,
                             plate=slow, deliver=lambda text: box.deliver("admin", text).id)
        assert len(box.unread("admin")) == len(events.pending("admin")) == 1
        assert "plate=UNKNOWN" in box.unread("admin")[0].body
        assert events.pending("admin")[0].item_status == "?"
    finally:
        gate.set()


def test_event_fields_survive_null_delivery_and_legacy_files(tmp_path):
    from shantytown.events import NullEvents
    null = NullEvents()
    event = null.persist("admin", CARD.name, "stop-failure", False,
                         kind="stop-failure", error="server_error",
                         error_details="fixture details", last_assistant_message="fixture message")
    assert null.drain("admin") == [event]
    assert null._events[0].kind == "stop-failure"
    assert null._events[0].error_details == "fixture details"
    assert null._events[0].last_assistant_message == "fixture message"
    old = {"to": "admin", "frm": CARD.name, "reason": None, "rose": False}
    directory = tmp_path / "events"
    directory.mkdir()
    (directory / "ev-1.json").write_text(json.dumps(old))
    restored = FilesEvents(directory).pending("admin")[0]
    assert restored.kind == "stop" and restored.error is None


@pytest.mark.parametrize("boundary", ["event-persist", "before-notify"])
@pytest.mark.parametrize("screen", ["❯ ", "● API Error: safeguards stopped the response\nreq_fixture\n❯ "])
def test_interrupted_primary_notification_reconciles_once_without_banner(tmp_path, monkeypatch, boundary, screen):
    setup_root(tmp_path)
    registry = FilesRegistry(tmp_path / "crew")
    registry.set(Agent(name="admin", role="administrator"))
    box = FilesInbox(tmp_path / "inbox")
    events = FilesEvents(tmp_path / "events")
    def interrupted(*a, **kw):
        raise OSError("fixture primary interrupted before notification reservation")
    with monkeypatch.context() as patch:
        if boundary == "event-persist":
            patch.setattr(events, "persist", interrupted)
        else:
            patch.setattr(safeguard, "notify", interrupted)
        with pytest.raises(OSError):
            stop_failure.capture(tmp_path, CARD.name, PAYLOAD, to="admin",
                events=events, plate=lambda n: (None, None),
                deliver=lambda text: box.deliver("admin", text).id)
    assert stop_failure.state(tmp_path, CARD.name) == "safeguard-blocked"
    assert box.unread("admin") == []
    monkeypatch.setattr(cli, "_registry", lambda a: registry)
    monkeypatch.setattr(cli, "_inbox", lambda *a, **kw: box)
    monkeypatch.setattr(cli, "_plate", lambda a: lambda n: [])
    report = SimpleNamespace(findings=[tend.Finding(CARD.name, "up", tend.SAFEGUARD_BLOCKED)])
    for expected in ([CARD.name], []):
        assert cli._safeguard_reports(SimpleNamespace(root=tmp_path), [CARD], report, NullPanes(screen)) == expected
    assert len(box.unread("admin")) == 1
    assert "req_fixture" in box.unread("admin")[0].body
    assert stop_failure.state(tmp_path, CARD.name) == "safeguard-blocked"


def test_missing_launch_metadata_preserves_existing_safety_hold(tmp_path):
    setup_root(tmp_path)
    stop_failure.capture(tmp_path, CARD.name, PAYLOAD, to="admin",
        events=FilesEvents(tmp_path / "events"), plate=lambda n: (None, None), deliver=lambda t: "receipt")
    (tmp_path / "launched" / (CARD.name + ".json")).unlink()
    assert stop_failure.state(tmp_path, CARD.name) == "safeguard-blocked"


@pytest.mark.parametrize("reservation", ["UNKNOWN", "pending"])
def test_primary_unconfirmed_notification_stays_loud_without_retry(tmp_path, monkeypatch, capsys, reservation):
    setup_root(tmp_path)
    registry = FilesRegistry(tmp_path / "crew")
    registry.set(Agent(name="admin", role="administrator"))
    calls = []
    def uncertain(text):
        calls.append(text)
        raise TimeoutError("fixture delivery may have committed")
    with pytest.raises(TimeoutError):
        stop_failure.capture(tmp_path, CARD.name, PAYLOAD, to="admin",
            events=FilesEvents(tmp_path / "events"), plate=lambda n: (None, None), deliver=uncertain)
    ledger = next((tmp_path / "safeguard-reports").glob("*.json"))
    value = json.loads(ledger.read_text()); value["state"] = reservation
    ledger.write_text(json.dumps(value))
    monkeypatch.setattr(cli, "_registry", lambda a: registry)
    monkeypatch.setattr(cli, "_inbox", lambda *a, **kw: pytest.fail("uncertain delivery retried"))
    monkeypatch.setattr(cli, "_plate", lambda a: lambda n: [])
    report = SimpleNamespace(findings=[tend.Finding(CARD.name, "up", tend.SAFEGUARD_BLOCKED)])
    for _ in range(2):
        assert cli._safeguard_reports(SimpleNamespace(root=tmp_path), [CARD], report, NullPanes("❯ ")) == []
    assert len(calls) == 1 and "UNKNOWN" in capsys.readouterr().err


# aegis-rr3: franklin's safeguard StopFailure reached the administrator while
# every ordinary stop that evening reached its lead. The failure hook must pick
# the recipient exactly as route_stop does for an ordinary stop.
def _main_with_lead(tmp_path, monkeypatch, lead_up):
    import io
    from shantytown import stop_event
    from shantytown.tier import LeadStatus
    setup_root(tmp_path)
    registry = FilesRegistry(tmp_path / "crew")
    registry.set(Agent(name="admin", role="administrator"))
    registry.set(Agent(name="fixture-lead", role="lead", pane="lead-pane", reports_to="admin"))
    registry.set(Agent(name=CARD.name, role="worker", pane=CARD.pane, reports_to="fixture-lead"))
    box = FilesInbox(tmp_path / "inbox")
    asked = []
    def lead_is_up(reg, panes):
        def up(name):
            asked.append(name)
            return LeadStatus(lead_up, "" if lead_up else "fixture-lead is DOWN (no pane)")
        return up
    monkeypatch.setenv("SHANTY_AGENT", CARD.name)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(stop_failure.sys, "stdin", io.StringIO(json.dumps(
        {**PAYLOAD, "hook_event_name": "StopFailure"})))
    monkeypatch.setattr(cli, "_inbox", lambda *a, **kw: box)
    monkeypatch.setattr(stop_event, "_lead_is_up", lead_is_up)
    monkeypatch.setattr(stop_event, "_plate_of", lambda root, name: ("fixture-item", "in_progress", []))
    assert stop_failure.main(["--root", str(tmp_path)]) == 0
    assert asked == ["fixture-lead"]  # the same live-lead predicate ordinary stops use
    return box, FilesEvents(tmp_path / "events")


def test_stop_failure_with_up_lead_reaches_the_lead_not_the_administrator(tmp_path, monkeypatch):
    box, events = _main_with_lead(tmp_path, monkeypatch, lead_up=True)
    assert len(box.unread("fixture-lead")) == 1
    assert box.unread("admin") == []
    [event] = events.pending("fixture-lead")
    assert event.kind == "stop-failure" and not event.rose
    assert events.pending("admin") == []


def test_stop_failure_with_down_lead_rises_to_the_administrator_loudly(tmp_path, monkeypatch):
    box, events = _main_with_lead(tmp_path, monkeypatch, lead_up=False)
    assert box.unread("fixture-lead") == []
    assert len(box.unread("admin")) == 1
    [event] = events.pending("admin")
    assert event.rose and "lead-unreachable" in event.detail
    assert events.pending("fixture-lead") == []


def test_route_recipient_says_no_to_the_administrator_when_the_lead_is_up(tmp_path):
    # The control must be able to fail: the old hard-coded answer is refused.
    registry = FilesRegistry(tmp_path / "crew")
    registry.set(Agent(name="admin", role="administrator"))
    registry.set(Agent(name="fixture-lead", role="lead", reports_to="admin"))
    registry.set(Agent(name="w", role="worker", reports_to="fixture-lead"))
    assert stop_failure.route_recipient(registry, "w", lambda n: True) == ("fixture-lead", False, None)
    to, rose, note = stop_failure.route_recipient(registry, "w", lambda n: False)
    assert (to, rose) == ("admin", True) and note
    registry.set(Agent(name="solo", role="worker"))  # no lead: administrator, not a rise
    assert stop_failure.route_recipient(registry, "solo", lambda n: True) == ("admin", False, None)


def test_route_recipient_falls_back_loudly_when_the_lead_card_is_missing(tmp_path, capsys):
    registry = FilesRegistry(tmp_path / "crew")
    registry.set(Agent(name="admin", role="administrator"))
    registry.set(Agent(name="w", role="worker", reports_to="ghost"))
    to, rose, note = stop_failure.route_recipient(registry, "w", lambda n: True)
    assert (to, rose) == ("admin", True) and "UNKNOWN" in note
    assert "fell back to administrator" in capsys.readouterr().err


# Review of #762: a routing read that raises something outside the lookup
# family (Quipu down for an off-host lead, a tmux error in the liveness probe)
# escaped to main's outer except BEFORE capture(), so the safeguard-blocked hold
# was never written and nobody was told. Both must fall back to the
# administrator with the hold intact.
def _main_with_broken_route(tmp_path, monkeypatch, capsys, break_at):
    import io
    from shantytown import routing_identity, stop_event
    setup_root(tmp_path)
    registry = FilesRegistry(tmp_path / "crew")
    registry.set(Agent(name="admin", role="administrator"))
    registry.set(Agent(name="fixture-lead", role="lead", pane="lead-pane", reports_to="admin"))
    registry.set(Agent(name=CARD.name, role="worker", pane=CARD.pane, reports_to="fixture-lead"))
    box = FilesInbox(tmp_path / "inbox")
    def boom(*a, **kw):
        raise RuntimeError("fixture backend down")
    def lead_is_up(reg, panes):
        return boom if break_at == "probe" else (lambda name: True)
    if break_at == "remote-lead":
        monkeypatch.setattr(routing_identity, "with_remote_lead", boom)
    monkeypatch.setenv("SHANTY_AGENT", CARD.name)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(stop_failure.sys, "stdin", io.StringIO(json.dumps(
        {**PAYLOAD, "hook_event_name": "StopFailure"})))
    monkeypatch.setattr(cli, "_inbox", lambda *a, **kw: box)
    monkeypatch.setattr(stop_event, "_lead_is_up", lead_is_up)
    monkeypatch.setattr(stop_event, "_plate_of", lambda root, name: ("fixture-item", "in_progress", []))
    assert stop_failure.main(["--root", str(tmp_path)]) == 0
    return box, FilesEvents(tmp_path / "events"), capsys.readouterr().err


@pytest.mark.parametrize("break_at", ["probe", "remote-lead"])
def test_route_error_keeps_the_hold_and_tells_the_administrator(tmp_path, monkeypatch, capsys, break_at):
    box, events, err = _main_with_broken_route(tmp_path, monkeypatch, capsys, break_at)
    assert stop_failure.state(tmp_path, CARD.name) == "safeguard-blocked"
    assert len(box.unread("admin")) == 1 and box.unread("fixture-lead") == []
    [event] = events.pending("admin")
    assert event.rose and "RuntimeError" in event.detail
    assert "fell back to administrator" in err
    assert "stop-failure UNKNOWN" not in err  # not swallowed by main's outer except


def test_route_recipient_falls_back_when_the_liveness_probe_raises(tmp_path, capsys):
    registry = FilesRegistry(tmp_path / "crew")
    registry.set(Agent(name="admin", role="administrator"))
    registry.set(Agent(name="fixture-lead", role="lead", reports_to="admin"))
    registry.set(Agent(name="w", role="worker", reports_to="fixture-lead"))
    def probe(name):
        raise OSError("fixture tmux socket gone")
    to, rose, note = stop_failure.route_recipient(registry, "w", probe)
    assert (to, rose) == ("admin", True) and "OSError" in note
