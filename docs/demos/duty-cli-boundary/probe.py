"""Observe the real stop handler with synthetic card, inbox and pane boundaries."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace


def one():
    sys.path.insert(0, str(Path.cwd()))
    import pytest
    from shantytown import cli
    from tests.test_stranded_adapter import setup
    from tests.test_stranded_duties import armed, install, record
    with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
        world = armed(setup.__wrapped__(Path(directory), patch), patch)
        install(world, [record()])
        world.panes.exists = lambda _: False
        for name, value in (('_registry', world.registry), ('_panes', world.panes),
                            ('_tracker', world.tracker), ('_inbox', world.inbox)):
            patch.setattr(cli, name, lambda _, value=value: value)
        stopped = []
        patch.setattr(cli, '_stop_locked', lambda _: stopped.append(True) or 0)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                args = cli.build_parser().parse_args(['agent', 'stop', 'worker', '--repool-work'])
                flag = args.repool_work
            except SystemExit:
                flag = False
            status = cli._cmd_stop(SimpleNamespace(root=world.root, agent='worker',
                dry_run=False, repool_work=False))
        return dict(explicit_repool_option=flag, ordinary_stop_exit=status,
                    stop_callback_called=bool(stopped), repair_count=len(world.repairs))


if __name__ == '__main__':
    if '--one' in sys.argv:
        print(json.dumps(one(), sort_keys=True))
    else:
        results = []
        for label, key in (('before', 'DEMO_BASE_SOURCE'), ('after', 'DEMO_HEAD_SOURCE')):
            raw = subprocess.check_output([sys.executable, str(Path(__file__).resolve()), '--one'],
                                          cwd=os.environ[key], text=True)
            result = json.loads(raw)
            print(label + ': ' + json.dumps(result, sort_keys=True), flush=True)
            results.append(result)
        assert results == [dict(explicit_repool_option=False, ordinary_stop_exit=0,
                                stop_callback_called=True, repair_count=0),
                           dict(explicit_repool_option=True, ordinary_stop_exit=1,
                                stop_callback_called=False, repair_count=0)]
        print('PASS: a held duty blocks the actual CLI stop; no live pane was stopped.')
