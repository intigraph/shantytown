"""Shared cache primitive: bounded complete observations, never decision authority."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
import pytest
from shantytown import crew_display_cache as cache

def validate(value):
    if not isinstance(value, dict) or value.get('complete') is not True:
        raise ValueError('incomplete fixture observation')

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
    return cache.read(key, build, validate=validate)


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


@pytest.mark.parametrize('kind', ['absolute', 'traversal'])
def test_cache_key_cannot_overwrite_file_outside_root(isolated, tmp_path, kind):
    sentinel = tmp_path / 'sentinel.json'
    sentinel.write_text('untouched')
    sentinel.chmod(0o600)
    before = sentinel.stat()
    key = str(tmp_path / 'sentinel') if kind == 'absolute' else '../sentinel'
    with pytest.raises(ValueError, match='UNKNOWN'):
        read(key=key)
    after = sentinel.stat()
    assert sentinel.read_text() == 'untouched'
    assert (after.st_ino, after.st_mtime_ns, after.st_mode) == (before.st_ino, before.st_mtime_ns, before.st_mode)
    assert {p.name for p in tmp_path.iterdir()} == {'cache', 'sentinel.json'}


@pytest.mark.parametrize('key', [
    '', 'a' * 63, 'a' * 65, 'A' * 64, 'g' * 64,
    '/' + 'a' * 63, '../' + 'a' * 61, 'a' * 31 + '\\' + 'a' * 32,
    '\uff41' * 64, None, b'a' * 64, 1,
])
def test_malformed_key_refuses_before_filesystem_or_producer(monkeypatch, key):
    monkeypatch.setattr(cache, 'directory', lambda: pytest.fail('invalid key reached filesystem'))
    monkeypatch.setattr(cache, 'boot_id', lambda: pytest.fail('invalid key read boot identity'))
    with pytest.raises(ValueError, match='UNKNOWN'):
        read(lambda: pytest.fail('invalid key reached producer'), key=key)
