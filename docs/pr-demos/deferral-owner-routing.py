"""Isolated source fixture: real sweep, fake transport, no external calls."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from shantytown.notify import DeferralAlerter
from shantytown.protocols import Agent


def main():
    now = datetime(2026, 1, 20, tzinfo=timezone.utc)
    deadline = (now - timedelta(days=10)).isoformat()
    cards = {name: Agent(name, role=role, reports_to=lead, pane=name)
             for name, role, lead in [('worker', 'worker', 'lead'),
                                      ('lead', 'lead', 'admin'),
                                      ('admin', 'administrator', None)]}
    print('Synthetic P0 date wait: overdue 10 days; external hold; no setter envelope.')
    for label, live in [('owner reachable', {'worker', 'lead'}),
                        ('owner down, lead reachable', {'lead'}),
                        ('both unreachable', set())]:
        row = dict(id='example-wait', status='deferred', assignee='worker',
                   title='External review', priority=0, labels=['blocked:external'],
                   updated_at=(now - timedelta(days=11)).isoformat(),
                   defer_until=deadline, notes='resume_when: date:' + deadline)
        sent, logs, releases = [], [], []
        def push(*args):
            sent.append('admin')
            return 'admin'
        panes = SimpleNamespace(exists=lambda pane: pane in live,
                                cmdline=lambda pane: 'claude --settings example.json',
                                send=lambda pane, text: sent.append(pane))
        with TemporaryDirectory() as root:
            alerter = DeferralAlerter(
                Path(root), SimpleNamespace(get=cards.__getitem__), panes,
                read=lambda: [row], show=lambda _: row, now=lambda: now,
                release=releases.append, push=push, log=logs.append)
            alerter.sweep()
            first = list(sent)
            alerter.sweep()
        reasons = [json.loads(line.split('deferral-route: ', 1)[1])['reason']
                   for line in logs if line.startswith('deferral-route: ')]
        print(f'{label}: recipients={first}; second pass adds={sent[len(first):]}; '
              f'reasons={reasons or ["not instrumented"]}; '
              f'hold={row["status"]}; releases={len(releases)}')
        expected = ('admin' if sys.argv[1] == 'before' or not live else
                    'worker' if 'worker' in live else 'lead')
        assert first == [expected] and sent == first
        assert row['status'] == 'deferred' and not releases


if __name__ == '__main__':
    main()
