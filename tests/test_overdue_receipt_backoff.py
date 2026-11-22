"""aegis-dnw: an unconfirmed reminder must not rescan the recipient inbox every tick."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import json

import pytest

from shantytown.answer import Answer
from shantytown.overdue import OverdueAlerter, receipt_recheck_due


class Registry:
    def all(self):
        return Answer.complete_read([SimpleNamespace(name="admin", role="administrator")], how="fixture")

    def get(self, name):
        if name not in ("admin", "worker"):
            raise LookupError(name)
        return SimpleNamespace(name=name)


def row():
    return dict(id="a-1", title="work", status="open", due_at="2026-10-01T00:00:00Z",
                assignee="worker", labels=[])


def harness(tmp_path, found=lambda: None):
    now = [datetime(2026, 10, 2, tzinfo=timezone.utc)]
    scans, sends = [], []

    def receipt(recipient, marker, identifier=None):
        scans.append((recipient, identifier, now[0]))
        return found()

    def sweep():
        return OverdueAlerter(tmp_path, Registry(), read=lambda: Answer.complete_read([row()], how="fixture"),
                              deliver=lambda *a: sends.append(a) or False, receipt=receipt,
                              now=lambda: now[0]).sweep()
    return now, scans, sends, sweep


def test_unconfirmed_packet_scan_backs_off_and_never_resends(tmp_path, monkeypatch):
    monkeypatch.delenv("ST_OVERDUE_RECEIPT_BACKOFF", raising=False)
    now, scans, sends, sweep = harness(tmp_path)
    assert sweep() == [] and len(sends) == 1  # ambiguous attempt; packet pending
    assert sweep() == [] and len(scans) == 1  # first re-check scans
    for _ in range(4):  # every 15-minute tick inside the 30 min wait: no scan
        now[0] += timedelta(minutes=7)
        assert sweep() == []
    assert len(scans) == 1
    now[0] += timedelta(minutes=2)  # 30 min after check 1
    assert sweep() == [] and len(scans) == 2
    now[0] += timedelta(minutes=59)
    assert sweep() == [] and len(scans) == 2
    now[0] += timedelta(minutes=1)  # 60 min after check 2
    assert sweep() == [] and len(scans) == 3
    packet = json.loads((tmp_path / "notify" / "overdue.json").read_text())["pending"]["worker"]
    assert packet["attempted"] is True and packet["receipt_checks"] == 3
    assert len(sends) == 1


def test_wait_is_capped_at_one_day():
    t = 1_000_000.0
    packet = {"receipt_checked_at": t, "receipt_checks": 40}
    assert not receipt_recheck_due(packet, t + 86399)
    assert receipt_recheck_due(packet, t + 86400)


def test_receipt_found_on_a_due_scan_settles_the_packet(tmp_path, monkeypatch):
    monkeypatch.delenv("ST_OVERDUE_RECEIPT_BACKOFF", raising=False)
    answer = [None]
    now, scans, sends, sweep = harness(tmp_path, found=lambda: answer[0])
    sweep(); sweep()
    answer[0] = "msg-1"
    now[0] += timedelta(minutes=30)
    sweep()
    ledger = json.loads((tmp_path / "notify" / "overdue.json").read_text())
    assert ledger["pending"] == {} and len(sends) == 1
    assert [v["receipt"] for v in ledger["entries"].values()] == ["msg-1"]


def test_backoff_zero_restores_a_scan_every_tick(tmp_path, monkeypatch):
    monkeypatch.setenv("ST_OVERDUE_RECEIPT_BACKOFF", "0")
    now, scans, sends, sweep = harness(tmp_path)
    for _ in range(4):
        sweep()
    assert len(scans) == 3 and len(sends) == 1


def test_known_receipt_id_check_is_not_backed_off(tmp_path, monkeypatch):
    monkeypatch.delenv("ST_OVERDUE_RECEIPT_BACKOFF", raising=False)
    now, scans, sends, sweep = harness(tmp_path)
    sweep()
    path = tmp_path / "notify" / "overdue.json"
    ledger = json.loads(path.read_text())
    ledger["pending"]["worker"].update(receipt_id="msg-9", receipt_checked_at=now[0].timestamp(),
                                       receipt_checks=5)
    path.write_text(json.dumps(ledger))
    sweep(); sweep()
    assert [s[1] for s in scans] == ["msg-9", "msg-9"]


@pytest.mark.parametrize("state", [{"receipt_checked_at": "x"}, {"receipt_checked_at": 1.0, "receipt_checks": True},
                                   {"receipt_checked_at": -1.0}])
def test_invalid_recheck_state_is_refused(state):
    with pytest.raises(ValueError):
        receipt_recheck_due(state, 10.0)


def test_future_checked_at_never_suppresses_a_scan():
    assert receipt_recheck_due({"receipt_checked_at": 500.0, "receipt_checks": 3}, 100.0)
