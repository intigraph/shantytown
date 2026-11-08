"""Display observations cannot replace live capacity or v1 peer admission."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from shantytown import cli, crew_display as display, crew_display_cache as cache, fleet
from shantytown.config import HostPeer


def payload():
    return dict(version=1, scope='local', host='box', complete=True, agents=[dict(
        name='worker', role='worker', state='up', work='idle', posture='auto',
        harness='codex', live=True, pane='pane', settings='current', tree='current')])


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    folder = tmp_path / 'cache'
    folder.mkdir(mode=0o700)
    monkeypatch.setattr(cache, 'directory', lambda: folder)
    monkeypatch.setattr(cache, 'boot_id', lambda: 'boot')
    return folder


def read(build=payload, key='a' * 64):
    return cache.read(key, build, validate=lambda value: display.validate_rows(value, 'box'))


def test_one_producer_for_concurrent_readers(isolated):
    count = 0
    lock = threading.Lock()
    def build():
        nonlocal count
        with lock:
            count += 1
        time.sleep(.05)
        return payload()
    def consumer(_):
        try:
            return read(build)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=100) as pool:
        values = list(pool.map(consumer, range(100)))
    assert count == 1
    assert any(values)
    assert read(lambda: pytest.fail('fresh observation must be shared'))['payload'] == payload()


def test_expiry_uses_oldest_observation_not_publication(isolated, monkeypatch):
    now = [100.]
    monkeypatch.setattr(cache.time, 'monotonic', lambda: now[0])
    def slow():
        now[0] += 16
        return payload()
    with pytest.raises(ValueError, match='UNKNOWN'):
        read(slow)
    assert not list(isolated.glob('*.json'))
    with pytest.raises(ValueError):
        read(lambda: pytest.fail('failed refresh backoff must suppress repeated reads'))


@pytest.mark.parametrize('mutation', ['expired', 'clock', 'boot', 'key', 'schema', 'payload'])
def test_invalid_saved_observation_cannot_be_returned(isolated, mutation):
    first = read()
    path = isolated / ('a' * 64 + '.json')
    if mutation == 'expired': first['started'] -= 16
    if mutation == 'clock': first['started'] += 100
    if mutation == 'boot': first['boot'] = 'previous-boot'
    if mutation == 'key': first['key'] = 'another-scope'
    if mutation == 'schema': first['schema'] = 1
    if mutation == 'payload': first['payload']['complete'] = False
    path.write_text(json.dumps(first))
    with pytest.raises(ValueError):
        read(lambda: (_ for _ in ()).throw(ValueError('unavailable')))


def test_failed_refresh_never_returns_expired_previous_rows(isolated, monkeypatch):
    read()
    monkeypatch.setattr(cache, 'TTL', 0)
    with pytest.raises(ValueError):
        read(lambda: (_ for _ in ()).throw(ValueError('unavailable')))


def test_crashed_producer_lease_released_and_old_data_not_promoted(isolated):
    with pytest.raises(ValueError):
        read(lambda: (_ for _ in ()).throw(RuntimeError('fixture crash')))
    (isolated / ('a' * 64 + '.failure')).unlink()
    assert read()['payload'] == payload()


def test_untrusted_directory_never_builds(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    path = tmp_path / 'shantytown' / 'crew-display-v2'
    path.mkdir(parents=True, mode=0o777)
    path.chmod(0o777)
    with pytest.raises(ValueError):
        read(lambda: pytest.fail('untrusted cache must not query'))


def test_symlink_lock_cannot_touch_target(isolated):
    target = isolated / 'target'
    target.write_text('untouched')
    (isolated / ('a' * 64 + '.lock')).symlink_to(target)
    with pytest.raises(ValueError):
        read(lambda: pytest.fail('symlink lock must not query'))
    assert target.read_text() == 'untouched'


def test_partial_and_oversized_producers_are_not_published(isolated):
    for build in (lambda: dict(payload(), complete=False),
                  lambda: dict(payload(), padding='x' * (cache.MAX_BYTES + 1))):
        with pytest.raises(ValueError):
            read(build)
        assert not list(isolated.glob('*.json'))
        for path in isolated.glob('*.failure'): path.unlink()


def test_live_v1_peer_rejects_display_protocol(monkeypatch):
    wire = dict(payload(), version=2, purpose='display', decision_eligible=False,
                ttl_seconds=15, age_seconds=0)
    monkeypatch.setattr(fleet.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout=json.dumps(wire), stderr=''))
    assert fleet.read_peer(HostPeer('box', 'peer', '/root'))['error']


@pytest.mark.parametrize('change', [dict(version=1), dict(decision_eligible=True),
    dict(age_seconds=16), dict(age_seconds=-1), dict(age_seconds=True),
    dict(host='wrong'), dict(complete=False), dict(agents=[{}])])
def test_display_peer_refuses_wrong_or_stale_envelope(monkeypatch, change):
    wire = dict(payload(), version=2, purpose='display', decision_eligible=False,
                ttl_seconds=15, age_seconds=0)
    wire.update(change)
    monkeypatch.setattr(display.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout=json.dumps(wire), stderr=''))
    assert display.read_peer(HostPeer('box', 'peer', '/root'))['complete'] is False


def test_display_peer_is_nonrecursive_and_accounts_for_transport_age(monkeypatch):
    wire = dict(payload(), version=2, purpose='display', decision_eligible=False,
                ttl_seconds=15, age_seconds=1)
    def run(argv, **kw):
        assert argv[-1].endswith('crew --json --local --display-snapshot')
        assert kw['timeout'] == 20
        return SimpleNamespace(returncode=0, stdout=json.dumps(wire))
    monkeypatch.setattr(display.subprocess, 'run', run)
    result = display.read_peer(HostPeer('box', 'peer', '/tmp/a b'))
    assert result['complete']
    assert result['age_seconds'] >= 1


def test_source_root_backend_and_roster_cards_separate_cache_keys(tmp_path):
    args = SimpleNamespace(root=tmp_path, backend='files', registry='files', repo=None)
    first = display.identity(args, 'box')
    (tmp_path / 'crew').mkdir()
    (tmp_path / 'crew' / 'new.json').write_text('{}')
    assert display.identity(args, 'box') != first
    first = display.identity(args, 'box')
    args.backend = 'seeds'
    assert display.identity(args, 'box') != first
    assert display.identity(args, 'other') != display.identity(args, 'box')


def test_cli_default_stays_live_and_display_decision_flags_refused(monkeypatch):
    args = SimpleNamespace(display_snapshot=True, governor=True)
    assert cli._cmd_crew(args) == 2
    parser = cli.build_parser()
    assert parser.parse_args(['crew']).display_snapshot is False
    with pytest.raises(SystemExit):
        parser.parse_args(['crew', '--display-snapshot', '--review-routing'])


def test_capacity_mutation_uses_live_owner_rows_not_display_or_frozen_render(monkeypatch):
    from shantytown.sd import SdTracker
    from shantytown import seeds_plate
    from shantytown.answer import Answer
    tracker = SdTracker()
    tracker._roster_capacity = {'worker': Answer.complete_read([], how='older empty display')}
    monkeypatch.setattr(tracker, '_use_remote_projection', lambda: True)
    monkeypatch.setattr(tracker, 'prove_store', lambda: 'proof')
    current = [dict(id='new-work', status='in_progress', assignee='worker')]
    monkeypatch.setattr(seeds_plate, 'owner_rows', lambda *a, **kw:
                        Answer.complete_read(current, how='live new assignment'))
    monkeypatch.setattr(cache, 'read', lambda *a, **kw: pytest.fail('decision touched display cache'))
    assert tracker.capacity_admission_rows('worker').exact() == current


def test_expired_local_observation_after_peer_delay_is_unknown(monkeypatch, tmp_path, capsys):
    clock = [10.]
    monkeypatch.setattr(display.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(display, 'local_snapshot', lambda a: dict(payload(), version=2,
        purpose='display', decision_eligible=False, age_seconds=0, errors=[], _received_at=10.))
    peer = HostPeer('box', 'peer', '/root')
    cfg = SimpleNamespace(host_peers={'box': peer})
    monkeypatch.setattr(cli.config, 'load_or_default', lambda root: (cfg, None))
    def slow_peer(peer):
        clock[0] = 30.
        return dict(payload(), errors=[], age_seconds=0, _received_at=30.)
    monkeypatch.setattr(display, 'read_peer', slow_peer)
    args = SimpleNamespace(root=tmp_path, local=False, json=False, count=True)
    assert display.command(args) == 3
    assert capsys.readouterr().out == 'UNKNOWN display snapshot\n'


def test_real_producer_and_local_v2_cli_on_an_empty_private_registry(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache-home'))
    args = SimpleNamespace(root=tmp_path / 'store', backend='files', registry='files',
                           repo=None, local=True, json=True, count=False)
    args.root.mkdir()
    with pytest.raises(ValueError):
        display.build_live(args)
    (args.root / 'crew').mkdir()
    result = display.build_live(args)
    assert result['version'] == 1
    assert result['agents'] == []
    assert display.command(args) == 0
    wire = json.loads(capsys.readouterr().out)
    assert wire['version'] == 2 and wire['decision_eligible'] is False
    assert wire['complete'] is True
    assert wire['agents'] == [] and wire['age_seconds'] < 15
    assert '_received_at' not in wire


@pytest.mark.skipif(__import__('sys').platform != 'linux', reason='deployed Linux cancellation contract')
def test_parent_death_cancels_producer_and_its_child(tmp_path):
    import os
    import signal
    import subprocess
    import sys
    ready = tmp_path / 'ready.json'
    # Stub the child CLI, not the cancellation setup. The actual producer code
    # must kill this entire private group when its requesting process dies.
    stub = f'''import sys,types,subprocess,pathlib,time,json,os
m=types.ModuleType('shantytown.cli')
def main():
 child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
 pathlib.Path({str(ready)!r}).write_text(json.dumps([os.getpid(),child.pid]))
 time.sleep(30)
m.main=main
sys.modules['shantytown.cli']=m
'''
    wrapper = f'''import subprocess,sys,time
from shantytown.crew_display import _producer_code
subprocess.Popen([sys.executable,'-c',{stub!r}+_producer_code()],start_new_session=True)
time.sleep(30)
'''
    parent = subprocess.Popen([sys.executable, '-c', wrapper], cwd=Path(display.__file__).parent.parent)
    pids = []
    def running(pid):
        try:
            return Path(f'/proc/{pid}/stat').read_text().split()[2] != 'Z'
        except FileNotFoundError:
            return False
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        pids = json.loads(ready.read_text())
        assert all(running(pid) for pid in pids)
        parent.kill()
        parent.wait(timeout=3)
        deadline = time.monotonic() + 3
        while any(running(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(.02)
        assert not any(running(pid) for pid in pids)
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=3)
        if pids:
            try:
                os.killpg(pids[0], signal.SIGKILL)
            except ProcessLookupError:
                pass
