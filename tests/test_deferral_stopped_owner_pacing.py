"""Deliberate scale-down produces one admin digest per owner, not lead fan-out."""
import copy
import json
from dataclasses import replace

from shantytown import deferrals
from shantytown.protocols import Agent
from shantytown.stopped import FilesStops
from test_deferral_owner_routing import NOW, harness


def stopped_batch(tmp_path, monkeypatch, counts):
    h = harness(tmp_path, monkeypatch)
    rows, findings = [], []
    for owner, count in counts.items():
        h.cards[owner] = Agent(owner, role='worker', reports_to='lead', pane=owner)
        FilesStops(tmp_path / 'stopped').record(owner, NOW.timestamp())
        for n in range(count):
            row = {**h.row, 'id': f'test-{owner}-{n}', 'assignee': owner,
                   'priority': n % 4, 'notes': 'private reason never copied into digest'}
            rows.append(row)
            findings.append(replace(h.finding, bead=row['id'], assignee=owner,
                                    priority=row['priority']))
    h.alerter._read = lambda: rows
    h.alerter._show = {row['id']: row for row in rows}.__getitem__
    monkeypatch.setattr(deferrals, 'evaluate', lambda *a, **kw: findings)
    h.rows, h.findings = rows, findings
    return h


def test_85_waits_for_stopped_owner_are_one_admin_digest_not_lead_wakes(tmp_path, monkeypatch):
    h = stopped_batch(tmp_path, monkeypatch, {'worker': 85})
    before = copy.deepcopy(h.rows)
    assert set(h.alerter.sweep()) == {row['id'] for row in h.rows}
    assert not h.sent
    assert len(h.admins) == 1
    text = h.admins[0]
    assert 'STOPPED-OWNER-PACING' in text and 'worker' in text and 'total=85' in text
    assert 'P0=22' in text and 'P1=21' in text and 'P2=21' in text and 'P3=21' in text
    assert all(row['id'] in text for row in h.rows if row['priority'] == 0)
    assert 'private reason' not in text
    assert h.rows == before  # notification does not un-defer or reassign work
    assert h.alerter.sweep() == [] and len(h.admins) == 1


def test_two_stopped_owners_get_separate_digests_and_retry_only_failed_owner(tmp_path, monkeypatch):
    h = stopped_batch(tmp_path, monkeypatch, {'worker': 5, 'other': 3})
    attempts = []
    def push(*args):
        text = args[-1]
        attempts.append(text)
        if 'owner=other ' in text:
            return None
        h.admins.append(text)
        return 'admin'
    h.alerter._push = push
    assert set(h.alerter.sweep()) == {row['id'] for row in h.rows if row['assignee'] == 'worker'}
    assert len(attempts) == 2 and len(h.admins) == 1 and not h.sent
    h.alerter._push = lambda *args: h.admins.append(args[-1]) or 'admin'
    assert set(h.alerter.sweep()) == {row['id'] for row in h.rows if row['assignee'] == 'other'}
    assert len(h.admins) == 2 and 'owner=other ' in h.admins[-1]
    assert h.alerter.sweep() == [] and len(h.admins) == 2


def test_large_p0_display_is_explicit_and_full_inventory_is_retained(tmp_path, monkeypatch):
    h = stopped_batch(tmp_path, monkeypatch, {'worker': 70})
    for row, finding in zip(h.rows, h.findings):
        row['priority'] = finding.priority = 0
    h.alerter.sweep()
    assert len(h.admins) == 1 and not h.sent
    assert 'P0=70' in h.admins[0] and '6 more' in h.admins[0]
    detail = json.loads((tmp_path / 'notify' / 'deferral-stopped-owners.json').read_text())
    assert set(detail['worker']['p0']) == {row['id'] for row in h.rows}


def test_cleared_stop_returns_reminders_to_actual_owner(tmp_path, monkeypatch):
    h = stopped_batch(tmp_path, monkeypatch, {'worker': 1})
    h.alerter.sweep()
    FilesStops(tmp_path / 'stopped').forget('worker')
    h.alerter.sweep()
    assert [pane for pane, _ in h.sent] == ['worker']
    assert len(h.admins) == 1 and h.rows[0]['status'] == 'deferred'


def test_lead_fallback_never_targets_another_worker(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, live=('lead',))
    h.cards['lead'] = replace(h.cards['lead'], role='worker')
    h.alerter.sweep()
    assert not h.sent and len(h.admins) == 1


def test_stopped_owner_authority_findings_share_the_digest_and_stay_visible(tmp_path, monkeypatch):
    h = stopped_batch(tmp_path, monkeypatch, {'worker': 3})
    h.findings[1].condition = deferrals.Condition('ruling', 'test-target')
    h.alerter.sweep()
    assert len(h.admins) == 1 and not h.sent
    assert 'total=3' in h.admins[0]
    assert 'Read-error/authority findings: test-worker-1' in h.admins[0]
    assert any('"reason": "authority-ruling"' in line for line in h.logs)


def test_failed_full_inventory_publication_does_not_consume_digest(tmp_path, monkeypatch):
    from shantytown import files
    h = stopped_batch(tmp_path, monkeypatch, {'worker': 1})
    original = files.write_json_atomic
    def fail_inventory(path, value):
        if path.name == 'deferral-stopped-owners.json':
            raise OSError('synthetic private disk failure')
        return original(path, value)
    monkeypatch.setattr(files, 'write_json_atomic', fail_inventory)
    assert h.alerter.sweep() == [] and not h.admins and not h.sent
    monkeypatch.setattr(files, 'write_json_atomic', original)
    assert h.alerter.sweep() == [h.rows[0]['id']]
    assert len(h.admins) == 1 and not h.sent
