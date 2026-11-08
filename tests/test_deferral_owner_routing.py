"""Routing notifications cannot grant release or hide urgent read failures."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from shantytown import deferrals
from shantytown.notify import DeferralAlerter
from shantytown.protocols import Agent

NOW = datetime(2026, 11, 8, 5, tzinfo=timezone.utc)


def harness(tmp_path, monkeypatch, *, live=("worker", "lead"), kind="date",
            met=True, read_error=False, priority=0, failed=(), admin_up=True):
    cards = {name: Agent(name, role=role, reports_to=lead, pane=name)
             for name, role, lead in [("worker", "worker", "lead"),
                                      ("lead", "lead", "admin"),
                                      ("admin", "administrator", None)]}
    sent, admins, logs = [], [], []
    row = {"id": "test-wait", "status": "deferred", "assignee": "worker",
           "priority": priority, "notes": "Additional judgement remains required",
           "defer_until": (NOW - timedelta(days=10)).isoformat(),
           "updated_at": (NOW - timedelta(days=11)).isoformat()}
    finding = deferrals.Finding(
        bead=row["id"], assignee="worker", priority=priority,
        lapsed_at=NOW - timedelta(days=10),
        condition=deferrals.Condition(kind, "test-target"), met=met and not read_error,
        read_error=read_error,
        untestable=("typed ruling evidence is UNKNOWN; retain hold; reason=binding)"
                    if read_error else ""))
    monkeypatch.setattr(deferrals, "evaluate", lambda *a, **kw: [finding])
    monkeypatch.setattr(deferrals, "can_release", lambda *a: False)
    def send(pane, text):
        if pane in failed:
            raise OSError("private transport detail")
        sent.append((pane, text))
    def push(*args):
        if admin_up:
            admins.append(args[-1])
            return "admin"
        return None
    panes = SimpleNamespace(exists=lambda pane: pane in live, send=send,
                            cmdline=lambda pane: "claude --settings /tmp/private/settings.json")
    alerter = DeferralAlerter(
        tmp_path, SimpleNamespace(get=cards.__getitem__), panes,
        read=lambda: [row], show=lambda _: row, now=lambda: NOW,
        push=push, log=logs.append)
    return SimpleNamespace(alerter=alerter, row=row, finding=finding,
                           sent=sent, admins=admins, logs=logs, cards=cards)


def test_legacy_ten_day_lapse_stays_with_live_owner_once(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch)
    assert h.alerter.sweep() == []
    assert [pane for pane, _ in h.sent] == ["worker"]
    assert h.admins == [] and h.row["status"] == "deferred"
    assert h.alerter.sweep() == [] and len(h.sent) == 1


def test_met_forge_gate_routes_to_owner_before_future_backstop(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, kind="ci-terminal", met=True)
    h.row["defer_until"] = (NOW + timedelta(days=1)).isoformat()
    h.alerter.sweep()
    assert [pane for pane, _ in h.sent] == ["worker"]
    assert not h.admins and h.row["status"] == "deferred"


@pytest.mark.parametrize("failed", [(), ("worker",)])
def test_owner_unreachable_or_delivery_failure_uses_lead(tmp_path, monkeypatch, failed):
    h = harness(tmp_path, monkeypatch, live=("lead",) if not failed else ("worker", "lead"),
                failed=failed)
    h.alerter.sweep()
    assert [pane for pane, _ in h.sent] == ["lead"]
    assert not h.admins


def test_stopped_owner_uses_live_lead(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch)
    stopped = tmp_path / "stopped"
    stopped.mkdir()
    (stopped / "worker.json").write_text('{}')
    h.alerter.sweep()
    assert [pane for pane, _ in h.sent] == ["lead"] and not h.admins


def test_both_unreachable_retains_one_admin_digest(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, live=())
    assert h.alerter.sweep() == [h.row["id"]]
    assert len(h.admins) == 1 and not h.sent
    h.alerter.sweep()
    assert len(h.admins) == 1
    assert any('owner-lead-unreachable' in line for line in h.logs)


@pytest.mark.parametrize("kind", ["ruling", "activation"])
def test_authority_gate_still_routes_to_admin(tmp_path, monkeypatch, kind):
    h = harness(tmp_path, monkeypatch, kind=kind, met=True)
    assert h.alerter.sweep() == [h.row["id"]]
    assert len(h.admins) == 1 and not h.sent
    assert any('authority-' + kind in line for line in h.logs)


def test_three_binding_failures_are_loud_even_for_low_priority(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, kind="activation", read_error=True, priority=3)
    for _ in range(2):
        assert h.alerter.sweep() == [] and not h.admins
    assert h.alerter.sweep() == [h.row["id"]]
    assert not h.sent and len(h.admins) == 1
    assert "UNTESTABLE" in h.admins[0]
    assert any('binding-failure' in line for line in h.logs)
    h.alerter.sweep()
    assert len(h.admins) == 1


def test_urgent_nonbinding_error_keeps_admin_route(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, kind="closed", read_error=True, priority=3)
    h.finding.untestable = "read failed"
    for _ in range(3):
        h.alerter.sweep()
    assert len(h.admins) == 1 and not h.sent
    assert any('urgent-read-error' in line for line in h.logs)


def test_admin_rows_bind_state_reason_and_digest_without_private_prose(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, kind="ruling", met=True)
    h.row["notes"] += " private-canary-value"
    h.alerter.sweep()
    records = [json.loads(line.split('deferral-route: ', 1)[1])
               for line in h.logs if 'deferral-route: ' in line]
    assert len(records) == 1
    [record] = records
    assert record['item'] == h.finding.bead and record['state_key'] == h.finding.key()
    assert record['reason'] == 'authority-ruling' and record['recipient'] == 'admin'
    assert record['outcome'] == 'delivered' and len(record['digest']) == 64
    assert len(record['source_sha256']) == 64
    assert not any('private-canary-value' in line for line in h.logs)


def test_failed_delivery_does_not_mark_a_notification_delivered(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, live=(), admin_up=False)
    assert h.alerter.sweep() == [] and not h.admins
    assert not any('ADMIN-DIGEST delivered' in line for line in h.logs)
    h.alerter._push = lambda *args: h.admins.append(args[-1]) or 'admin'
    assert h.alerter.sweep() == [h.row['id']] and len(h.admins) == 1


def test_low_priority_ordinary_event_still_reaches_owner(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, priority=3)
    assert h.alerter.sweep() == []
    assert [pane for pane, _ in h.sent] == ['worker'] and not h.admins


def test_unreadable_source_identity_does_not_drop_authority_digest(tmp_path, monkeypatch):
    from pathlib import Path
    h = harness(tmp_path, monkeypatch, kind='ruling', met=True)
    original = Path.read_bytes
    def read(path):
        if path.name == 'deferral_pacing.py':
            raise OSError('private-source-location')
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', read)
    assert h.alerter.sweep() == [h.row['id']]
    assert len(h.admins) == 1 and not h.sent
    assert any('"source_sha256": "UNKNOWN"' in line for line in h.logs)
    assert not any('private-source-location' in line for line in h.logs)


def test_owner_and_stopped_lead_escalate_without_delivery_claim(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, live=('lead',))
    stopped = tmp_path / 'stopped'
    stopped.mkdir()
    (stopped / 'lead.json').write_text('{}')
    assert h.alerter.sweep() == [h.row['id']]
    assert not h.sent and len(h.admins) == 1
    assert any('owner-lead-unreachable' in line for line in h.logs)


def test_administrator_is_not_a_quiet_lead_fallback(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, live=('admin',))
    h.cards['worker'] = replace(h.cards['worker'], reports_to='admin')
    assert h.alerter.sweep() == [h.row['id']]
    assert not h.sent and len(h.admins) == 1
    assert any('owner-lead-unreachable' in line for line in h.logs)
