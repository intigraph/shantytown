"""Real isolated subprocesses, no network or production credential reads."""
import argparse
import json
import sys
import time

import pytest

from shantytown import memory_cli, memory_deadline as deadline
from shantytown.memory_remote import Unproven


def _fixture_process_exited(pid):
    from pathlib import Path
    try:
        state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        # Linux can report ENOENT on open or ESRCH during read as a task exits.
        return True
    return state in {'Z', 'X'}


@pytest.mark.parametrize('error', [FileNotFoundError, ProcessLookupError])
def test_fixture_process_exit_during_stat_read(monkeypatch, error):
    from pathlib import Path
    def gone(path):
        assert str(path) == '/proc/123/stat'
        raise error('fixture process disappeared during read')
    monkeypatch.setattr(Path, 'read_text', gone)
    assert _fixture_process_exited(123)


@pytest.mark.parametrize('state,exited', [('R', False), ('S', False), ('Z', True), ('X', True)])
def test_fixture_process_stat_state(monkeypatch, state, exited):
    from pathlib import Path
    monkeypatch.setattr(Path, 'read_text', lambda path: f'123 (worker name) {state} 1')
    assert _fixture_process_exited(123) is exited


@pytest.mark.parametrize('error', [PermissionError, OSError, ValueError])
def test_fixture_process_stat_unrelated_error_remains_unknown(monkeypatch, error):
    from pathlib import Path
    def unreadable(path):
        raise error('not proof of process exit')
    monkeypatch.setattr(Path, 'read_text', unreadable)
    with pytest.raises(error):
        _fixture_process_exited(123)


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


def test_inspect_command_has_separate_one_second_worker_budget(monkeypatch, capsys):
    args = argparse.Namespace(memory_action='inspect')
    seen = []
    monkeypatch.setattr(deadline, 'run_inspect', lambda value: seen.append(value) or {'files': []})
    monkeypatch.setattr(memory_cli, 'execute', lambda _: pytest.fail('unbounded scan'))
    assert memory_cli.command(args) == 0
    assert seen == [args]
    assert json.loads(capsys.readouterr().out) == {'files': []}


def test_actual_inspect_worker_preserves_full_128_file_metadata_without_bodies(tmp_path):
    source = tmp_path / 'native'
    source.mkdir()
    for number in range(128):
        (source / f'topic-{number}.md').write_text('private synthetic λ\r\n')
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in source.iterdir()}
    args = argparse.Namespace(directory=source)
    result = deadline.run_inspect(args)
    assert len(result['files']) == 128
    assert result['coverage'] == 'explicit_directory_snapshot'
    assert result['native_selection'] == 'UNCHANGED'
    assert 'private synthetic' not in json.dumps(result)
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in source.iterdir()} == before


def test_inspect_wire_uses_one_second_not_sync_budget(tmp_path, monkeypatch):
    seen = []
    def supervise(command, payload, **options):
        seen.append((json.loads(payload), options))
        return {'files': []}
    monkeypatch.setattr(deadline, '_supervise', supervise)
    deadline.run_inspect(argparse.Namespace(directory=tmp_path))
    envelope, options = seen.pop()
    assert envelope['action'] == 'inspect'
    assert options == dict(seconds=1.0, watch_parent=True, result_limit=32768)


def test_real_one_second_scan_budget_refuses_late_worker(tmp_path):
    command = worker(tmp_path, 'import time; time.sleep(20)')
    before = time.monotonic()
    with pytest.raises(Unproven, match='outcome unknown'):
        deadline._supervise(command, b'{}', seconds=1)
    assert 0.9 <= time.monotonic() - before < 2


def test_worker_without_exclusive_parent_channel_refuses_before_work(tmp_path):
    import subprocess
    result = subprocess.run([sys.executable, '-m', 'shantytown.memory_deadline'],
                            input=b'{}', capture_output=True, timeout=2)
    assert result.returncode == 2
    assert result.stdout == result.stderr == b''


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux process-state observation only')
@pytest.mark.parametrize('pid_write_pause', [0, 0.05])
def test_actual_parent_sigkill_stops_only_its_isolated_worker(tmp_path, pid_write_pause):
    import os
    from pathlib import Path
    import signal
    import subprocess
    # Existence is the readiness fence: publish only a fully written PID.
    # The delayed case keeps creation and publication observably separate.
    ready = tmp_path / 'worker-ready'
    command = worker(tmp_path, f'''import os, sys, time
from shantytown.memory_deadline import _watch_parent
_watch_parent(int(sys.argv[2]))
with open({str(ready)!r} + '.pending', 'x') as stream:
    time.sleep({pid_write_pause})
    stream.write(str(os.getpid()))
    stream.flush()
    os.fsync(stream.fileno())
os.rename({str(ready)!r} + '.pending', {str(ready)!r})
time.sleep(30)
''')
    parent_script = tmp_path / 'parent.py'
    parent_script.write_text(f'''from shantytown.memory_deadline import _supervise
_supervise({command!r}, b'{{}}', watch_parent=True)
''')
    # PYTHONPATH points at this isolated source, never installed runtime code.
    env = dict(os.environ, PYTHONPATH=str(Path(deadline.__file__).parent.parent))
    parent = subprocess.Popen([sys.executable, str(parent_script)], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid = None
    try:
        end = time.monotonic() + 1.5
        while not ready.exists() and time.monotonic() < end:
            time.sleep(0.01)
        assert ready.exists(), 'worker did not reach positive ready control'
        pid = int(ready.read_text())
        assert os.getpgid(pid) == pid
        assert parent.poll() is None
        os.kill(parent.pid, signal.SIGKILL)
        parent.wait(timeout=1)
        end = time.monotonic() + 1
        while time.monotonic() < end:
            if _fixture_process_exited(pid):  # Orphan reaping belongs to PID1.
                break
            time.sleep(0.01)
        else:
            pytest.fail('worker remained executing after caller death')
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=1)
        if pid is not None:
            # This is only the exact newly-created fixture group, never a
            # service/crew PID. No surviving test process is left behind.
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
