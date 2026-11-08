"""Compare recipient flaps using real sweeps and private temporary storage."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import shantytown.deferral_pacing as pacing
from shantytown.notify import DeferralAlerter
from shantytown.protocols import Agent

BASE = 'dac719b21cfe20131db588a1d8a1c199fb70206d'


def main():
    namespace = {'__package__': 'shantytown'}
    source = subprocess.check_output(
        ['git', 'show', f'{BASE}:shantytown/deferral_pacing.py'], text=True)
    exec(compile(source, 'before_deferral_pacing.py', 'exec'), namespace)
    now = datetime(2026, 1, 20, tzinfo=timezone.utc)
    cards = {name: Agent(name, role=role, reports_to=lead, pane=name)
             for name, role, lead in [('worker', 'worker', 'lead'),
                                      ('lead', 'lead', 'admin')]}
    print('Same external hold; owner -> lead -> owner -> lead -> owner; restart every sweep.')
    for label, implementation in [('before', namespace['OwnerPacing']),
                                  ('after', pacing.OwnerPacing)]:
        row = dict(id='example-wait', status='deferred', assignee='worker',
                   priority=0, labels=['blocked:external'],
                   updated_at=(now - timedelta(days=11)).isoformat(),
                   defer_until=(now - timedelta(days=10)).isoformat())
        row['notes'] = 'resume_when: date:' + row['defer_until']
        sent, releases = [], []
        with TemporaryDirectory() as root, patch.object(pacing, 'OwnerPacing', implementation):
            for live in [{'worker', 'lead'}, {'lead'}, {'worker', 'lead'},
                         {'lead'}, {'worker', 'lead'}]:
                panes = SimpleNamespace(exists=lambda pane: pane in live,
                                        cmdline=lambda _: 'claude --settings example.json',
                                        send=lambda pane, _: sent.append(pane))
                DeferralAlerter(Path(root), SimpleNamespace(get=cards.__getitem__), panes,
                                read=lambda: [row], show=lambda _: row, now=lambda: now,
                                release=releases.append,
                                push=lambda *_: sent.append('admin') or 'admin',
                                log=lambda _: None).sweep()
        print(f'{label}: recipients={sent}; hold={row["status"]}; releases={len(releases)}')
        assert sent == (['worker', 'lead'] * 2 + ['worker'] if label == 'before'
                        else ['worker', 'lead'])
        assert row['status'] == 'deferred' and not releases


if __name__ == '__main__':
    main()
