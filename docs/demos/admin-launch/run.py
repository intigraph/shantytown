"""Compare isolated launch-policy probes; never starts a session or reads credentials."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


def probe():
    sys.path.insert(0, os.environ['DEMO_SOURCE'])
    from types import SimpleNamespace
    from unittest.mock import patch
    from shantytown import cli, gaming
    from shantytown.files import FilesRegistry
    from shantytown.protocols import Agent
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        reg = FilesRegistry(root / 'crew')
        admin = Agent('operator', role='administrator')
        worker = Agent('worker', role='worker')
        reg.set(admin)
        reg.set(worker)
        gaming.manual(root)
        result = {}
        for card in (admin, worker):
            args = SimpleNamespace(root=root, cmd='new', agent=card.name,
                                   despite_hold=False)
            with patch.object(cli, '_registry', return_value=reg), \
                    patch.object(cli, '_cmd_new', return_value=0), \
                    contextlib.redirect_stderr(io.StringIO()):
                result[card.role + '_gaming_exit'] = cli._run_command(args)
            with patch.object(cli, '_registry', return_value=reg), \
                    patch.object(cli, '_governors', side_effect=RuntimeError('unavailable')):
                result[card.role + '_unknown_peer_refused'] = bool(
                    cli._account_launch_refusal(args, card))
        result['live_launches'] = 0
        print(json.dumps(result, sort_keys=True))


def compare():
    root = Path(__file__).resolve().parents[3]
    base = sys.argv[1] if len(sys.argv) > 1 else '2c880419efcdd25b91dcf49c0aa6c539c8ad631d'
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / 'base.tar'
        with archive.open('wb') as output:
            subprocess.run(['git', 'archive', base, 'shantytown'], cwd=root,
                           stdout=output, check=True)
        with tarfile.open(archive) as handle:
            handle.extractall(directory, filter='data')
        for label, source in [('base', Path(directory)), ('candidate', root)]:
            print(label, flush=True)
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--probe'],
                           env=dict(os.environ, DEMO_SOURCE=str(source)), check=True)


if __name__ == '__main__':
    probe() if '--probe' in sys.argv else compare()
