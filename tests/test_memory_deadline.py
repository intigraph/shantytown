"""Real isolated subprocesses, no network or production credential reads."""
import argparse
import json
import sys
import time

import pytest

from shantytown import memory_cli, memory_deadline as deadline
from shantytown.memory_remote import Unproven


def worker(tmp_path, source):
    path = tmp_path / 'worker.py'
    path.write_text(source)
    return [sys.executable, str(path)]


def test_on_time_positive_control(tmp_path):
    command = worker(tmp_path, 'print(\'{"result":{"status":"accepted"}}\')')
    assert deadline._supervise(command, b'{}', seconds=1) == {'status': 'accepted'}


def test_timeout_retains_durable_evidence_no_second_invocation(tmp_path):
    evidence = tmp_path / 'accepted-intent'
    command = worker(tmp_path, f'''import os, time
with open({str(evidence)!r}, 'xb') as stream:
    stream.write(b'committed-before-lost-reply')
    stream.flush()
    os.fsync(stream.fileno())
time.sleep(20)
''')
    before = time.monotonic()
    with pytest.raises(Unproven, match='outcome unknown'):
        deadline._supervise(command, b'{}', seconds=0.2)
    elapsed = time.monotonic() - before
    assert 0.18 <= elapsed < 1, elapsed
    assert evidence.read_bytes() == b'committed-before-lost-reply'
    # The exclusive file would reject a hidden second worker; metadata remains.
    assert set(tmp_path.iterdir()) == {tmp_path / 'worker.py', evidence}


@pytest.mark.parametrize('source', [
    'raise SystemExit(2)',
    'print("private malformed result")',
    'print(\'{"result":null}\')',
    'print(\'{"result":{},"extra":1}\')',
    'print("x"*4097)',
])
def test_refused_malformed_or_oversize_never_success(tmp_path, source):
    with pytest.raises(Unproven):
        deadline._supervise(worker(tmp_path, source), b'{}', seconds=1)


@pytest.mark.parametrize('seconds', [0, -1, 3, True, float('nan'), float('inf')])
def test_invalid_budget_does_not_start_worker(monkeypatch, seconds):
    monkeypatch.setattr(deadline.subprocess, 'Popen', lambda *a, **k: pytest.fail('started'))
    with pytest.raises(Unproven):
        deadline._supervise([], b'{}', seconds=seconds)


def test_sync_command_routes_through_supervisor(monkeypatch, capsys):
    args = argparse.Namespace(memory_action='sync')
    seen = []
    monkeypatch.setattr(deadline, 'run_sync', lambda value: seen.append(value) or {'status': 'pending'})
    monkeypatch.setattr(memory_cli, 'execute', lambda _: pytest.fail('unbounded sync'))
    assert memory_cli.command(args) == 0
    assert seen == [args]
    assert json.loads(capsys.readouterr().out) == {'status': 'pending'}


def test_exact_worker_refuses_missing_identity_without_network(tmp_path):
    # Missing scope refuses before credential selection/provider access.
    args = argparse.Namespace(root=tmp_path, agent='synthetic', server=None,
        deployment=None, project=None, owner=None, directory=tmp_path,
        outbox=tmp_path, harness='synthetic', account='synthetic', max_new=1)
    with pytest.raises(Unproven):
        deadline.run_sync(args)
    assert list(tmp_path.iterdir()) == []


def test_real_default_two_second_budget(tmp_path):
    command = worker(tmp_path, 'import time; time.sleep(20)')
    before = time.monotonic()
    with pytest.raises(Unproven, match='outcome unknown'):
        deadline._supervise(command, b'{}')
    elapsed = time.monotonic() - before
    assert 1.9 <= elapsed < 3.3, elapsed


def test_late_finished_worker_is_unknown_without_signalling_reaped_pid(tmp_path, monkeypatch):
    from types import SimpleNamespace
    ticks = iter((0.0, 0.0, 3.0))
    monkeypatch.setattr(deadline, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(deadline.os, 'killpg', lambda *a: pytest.fail('signalled reaped PID'))
    command = worker(tmp_path, 'print(\'{"result":{"status":"accepted"}}\')')
    with pytest.raises(Unproven, match='outcome unknown'):
        deadline._supervise(command, b'{}')
