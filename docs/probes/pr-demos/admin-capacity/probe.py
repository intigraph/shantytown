from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import pytest
from shantytown import cli
from test_fleet_governor import fleet_setup, sample, agent

with TemporaryDirectory(prefix='qmluma-probe-') as directory, pytest.MonkeyPatch.context() as mp:
    args = fleet_setup(Path(directory), mp, sample(cap=3, agents=[agent('desktop', 'remote')]))
    args.despite_hold = True
    reg = cli._registry(args)
    local = reg.get('local')
    admin = replace(local, name='admin', pane='admin-pane', role='administrator', reports_to=None)
    reg.set(admin)
    extra = replace(local, name='extra', pane='extra-pane')
    reg.set(extra)
    rows = [agent('laptop', 'local')]
    mp.setattr(cli, '_governor_agents', lambda a: list(rows))
    worker_refusal = cli._account_launch_refusal(args, extra)
    if not worker_refusal:
        rows.append(agent('laptop', 'extra'))
    admin_refusal = cli._account_launch_refusal(args, admin)
    print(json.dumps({'despite_hold': args.despite_hold, 'cap': 3,
                      'worker_consumed_final_slot': not bool(worker_refusal),
                      'worker_refusal': worker_refusal,
                      'admin_admitted': not bool(admin_refusal),
                      'admin_refusal': admin_refusal,
                      'live_before_admin': len(rows) + 1}, indent=2))
