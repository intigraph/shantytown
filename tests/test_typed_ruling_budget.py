"""Observation capacity never counts as a failed activation evidence read."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from shantytown import feed_check
from shantytown.answer import Answer
from shantytown.notify import DeferralAlerter
from shantytown.protocols import Agent
from shantytown.tmux import NullPanes


NOW = datetime(2026, 11, 6, 4, tzinfo=timezone.utc)
CREW = [Agent('admin', role='administrator'), Agent('lead', role='lead'),
        Agent('worker', reports_to='lead')]
REG = SimpleNamespace(all=lambda: Answer.complete_read(CREW, how='fixture'),
                      get=lambda name: next(a for a in CREW if a.name == name))


def waiting(index):
    item = f'item-{index:02}'
    until = '2026-11-07T05:00:00Z'
    kind = 'activation' if index % 2 else 'ruling'
    provenance = json.dumps(dict(actor='worker', set_at='2026-11-06T03:00:00Z', until=until))
    return dict(id=item, title='fixture', assignee='worker', priority=1,
                status='deferred', labels=['blocked:external'], defer_until=until,
                notes=f'resume_when: {kind}:{item}\ndefer_provenance: {provenance}')


def sweep(root, rows, now, monkeypatch, comments):
    sent, logs = [], []
    monkeypatch.setattr(feed_check, 'backend_adapter',
                        lambda *a: SimpleNamespace(ruling_comments=comments))
    by_id = {row['id']: row for row in rows}
    DeferralAlerter(root, REG, NullPanes(), read=lambda: rows,
        show=by_id.__getitem__, now=now,
        release=lambda _: pytest.fail('unproved activation must remain held'),
        push=lambda _r, _p, text: sent.append(text) or 'admin', log=logs.append).sweep()
    retries = json.loads((root / 'notify/deferral-retries.json').read_text())
    return sent, logs, retries


def test_unobserved_typed_gates_preserve_failures_without_alert_or_reset(tmp_path, monkeypatch):
    rows = [waiting(i) for i in range(15)]
    path = tmp_path / 'notify/deferral-retries.json'
    path.parent.mkdir()
    path.write_text(json.dumps({row['id']: 2 for row in rows}))
    observed = []
    sent, logs, retries = sweep(tmp_path, rows, NOW, monkeypatch,
                               lambda item: observed.append(item) or [])
    skipped = {row['id'] for row in rows} - set(observed)
    assert len(observed) == 12 and len(skipped) == 3
    assert retries == {item: 2 for item in skipped}
    assert not sent
    assert all(any(item in line and 'observation budget deferred' in line
                   for line in logs) for item in skipped)


def test_typed_observation_rotation_reaches_every_gate_without_more_reads(tmp_path, monkeypatch):
    rows = [waiting(i) for i in range(15)]
    seen = set()
    for tick in range(4):
        observed = []
        sent, _, retries = sweep(tmp_path, rows, NOW + timedelta(minutes=5 * tick),
                                  monkeypatch, lambda item: observed.append(item) or [])
        assert len(observed) == 12
        assert not sent and not retries
        seen.update(observed)
    assert seen == {row['id'] for row in rows}


def test_real_comment_errors_still_alert_after_three_passes_without_private_text(tmp_path, monkeypatch):
    def unavailable(_):
        raise RuntimeError('PRIVATE-COMMENT-TRANSPORT-CONTENT')
    deliveries, messages = [], []
    for _ in range(4):
        sent, logs, retries = sweep(tmp_path, [waiting(1)], NOW, monkeypatch, unavailable)
        deliveries.extend(sent)
        messages.extend(logs)
        assert retries['item-01'] >= 1
    assert len(deliveries) == 1 and '3 consecutive' in deliveries[0]
    assert any('reason=comments' in line for line in messages)
    assert all('PRIVATE-COMMENT' not in line for line in messages + deliveries)
