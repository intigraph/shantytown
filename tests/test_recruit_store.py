"""Private fixtures only; production never weakens ancestor or inode checks."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
import sqlite3
import stat
import sys
import threading

import pytest

from shantytown.actor_identity import IdentityError
from shantytown import recruit_request as rr, recruit_store as rs


pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux directory-FD backend')


@pytest.fixture
def private_store(tmp_path, monkeypatch):
    # CI/guard fixture namespaces may themselves be beneath a mutable /tmp or
    # group-writable harness directory. Model immutable OUTER ancestors only;
    # every created controller directory/file and every nofollow open is real.
    fstat = os.fstat
    outer = {(p.stat().st_dev, p.stat().st_ino) for p in tmp_path.parents
             if p.stat().st_mode & 0o022}
    def fixture_ancestry(fd):
        meta = fstat(fd)
        if (meta.st_dev, meta.st_ino) in outer:
            fields = list(meta)
            fields[0] &= ~0o022
            return os.stat_result(fields)
        return meta
    monkeypatch.setattr(rs.os, 'fstat', fixture_ancestry)
    root = tmp_path / 'controller'
    directory = root / 'ephemeral' / 'recruitment'
    root.mkdir(mode=0o700)
    (root / 'ephemeral').mkdir(mode=0o700)
    directory.mkdir(mode=0o700)
    pin = rr.Binding('fixture-recruiter', os.geteuid() + 10001, 'fixture-host',
                     ('intigraph/widget',), b'x' * 32, str(root))
    return pin, directory


def body(pin, **changes):
    value = dict(schema=rr.SCHEMA, principal=pin.principal, uid=pin.uid, host=pin.host,
                 verb='launch', job='review', item='task-1', repo='intigraph/widget', pr=42,
                 head='a'*40, target=None, nonce='b'*64, issued_at=100, expires_at=160)
    return value | changes


def test_private_store_reopens_and_nonce_is_not_rearmed(private_store):
    pin, directory = private_store
    with rs.Store(pin) as store:
        store.reserve(pin.principal, 'b'*64)
        assert store.db.execute('PRAGMA synchronous').fetchone() == (3,)
        assert store.db.execute('PRAGMA journal_mode').fetchone() == ('delete',)
        assert store.db.execute('PRAGMA max_page_count').fetchone() == (16384,)
    assert stat.S_IMODE((directory / rs.NAME).stat().st_mode) == 0o600
    with rs.Store(pin) as store:
        with pytest.raises(IdentityError, match='replay'):
            store.reserve(pin.principal, 'b'*64)
        assert store.db.execute('SELECT count(*) FROM nonces').fetchone() == (1,)


def test_concurrent_consumers_have_one_nonce_winner(private_store):
    pin, _ = private_store
    with rs.Store(pin): pass
    opened = threading.Lock()
    barrier = threading.Barrier(2)
    def reserve():
        with opened:
            store = rs.Store(pin)
        try:
            barrier.wait(timeout=3)
            try:
                store.reserve(pin.principal, 'b'*64)
                return 'reserved'
            except IdentityError:
                return 'refused'
        finally:
            store.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve) for _ in range(2)]
        assert sorted(f.result(timeout=5) for f in futures) == ['refused', 'reserved']


def test_claim_survives_lost_reply_and_fresh_nonce_cannot_duplicate_candidate(private_store):
    pin, _ = private_store
    first = body(pin)
    with rs.Store(pin) as store:
        store.reserve(pin.principal, first['nonce'])
        operation = store.claim(first)
    with rs.Store(pin) as store:
        assert store.db.execute('SELECT state FROM operations WHERE id=?', (operation,)).fetchone() == ('claimed',)
        with pytest.raises(IdentityError, match='already claimed'):
            store.claim(first)
        second = body(pin, nonce='c'*64)
        store.reserve(pin.principal, second['nonce'])
        with pytest.raises(IdentityError, match='already claimed'):
            store.claim(second)
        store.finish(operation, prepared=True, plan_digest='d'*64)
        with pytest.raises(IdentityError, match='terminal'):
            store.finish(operation)


def test_capacity_refuses_without_pruning_prior_nonce(private_store, monkeypatch):
    pin, _ = private_store
    monkeypatch.setattr(rs, 'MAX_ROWS', 1)
    with rs.Store(pin) as store:
        store.reserve(pin.principal, 'b'*64)
        with pytest.raises(IdentityError, match='capacity'):
            store.reserve(pin.principal, 'c'*64)
        assert store.db.execute('SELECT nonce FROM nonces').fetchall() == [('b'*64,)]


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'broad-mode', 'fifo'])
def test_unsafe_database_inode_is_refused(private_store, kind):
    pin, directory = private_store
    with rs.Store(pin): pass
    path = directory / rs.NAME
    if kind == 'symlink':
        path.rename(directory.parent / 'retained-original')
        path.symlink_to(directory.parent / 'retained-original')
    elif kind == 'hardlink':
        os.link(path, directory.parent / 'second-link')
    elif kind == 'broad-mode':
        path.chmod(0o640)
    else:
        path.unlink()
        os.mkfifo(path, 0o600)
    with pytest.raises((IdentityError, OSError)):
        rs.Store(pin)


@pytest.mark.parametrize('kind', ['broad-mode', 'symlink', 'mutable-parent'])
def test_unsafe_directory_or_parent_is_refused(private_store, kind):
    pin, directory = private_store
    if kind == 'broad-mode': directory.chmod(0o755)
    elif kind == 'symlink':
        directory.rename(directory.parent / 'retained')
        directory.symlink_to(directory.parent / 'retained', target_is_directory=True)
    else: directory.parent.chmod(0o770)
    with pytest.raises((IdentityError, OSError)):
        rs.Store(pin)


@pytest.mark.parametrize('kind', ['empty', 'corrupt', 'foreign-schema', 'unexpected-entry'])
def test_unproved_state_is_not_reinitialized(private_store, kind):
    pin, directory = private_store
    path = directory / rs.NAME
    if kind == 'empty': path.touch(mode=0o600)
    elif kind == 'corrupt':
        path.write_bytes(b'corrupt fixture')
        path.chmod(0o600)
    elif kind == 'foreign-schema':
        db = sqlite3.connect(path)
        db.execute('CREATE TABLE retained (value TEXT)')
        db.execute("INSERT INTO retained VALUES ('prior evidence')")
        db.commit();db.close();path.chmod(0o600)
    else:
        (directory / 'unexpected').touch(mode=0o600)
    with pytest.raises((IdentityError, sqlite3.DatabaseError)):
        rs.Store(pin)
    if kind == 'corrupt': assert path.read_bytes() == b'corrupt fixture'
    if kind == 'foreign-schema':
        db = sqlite3.connect(path)
        try: assert db.execute('SELECT * FROM retained').fetchall() == [('prior evidence',)]
        finally: db.close()


def test_missing_provisioned_directory_and_wrong_principal_refuse(private_store):
    pin, directory = private_store
    with pytest.raises(OSError):
        rs.Store(replace(pin, root=str(directory / 'absent')))
    assert not (directory / 'absent').exists()
    with rs.Store(pin) as store:
        with pytest.raises(IdentityError, match='identity'):
            store.reserve('another-principal', 'b'*64)
        with pytest.raises(IdentityError, match='not reserved'):
            store.claim(body(pin))


def test_process_exit_after_claim_retains_durable_reservation(private_store):
    pin, _ = private_store
    child = os.fork()
    if child == 0:
        try:
            store = rs.Store(pin)
            request = body(pin)
            store.reserve(pin.principal, request['nonce'])
            store.claim(request)
        except BaseException:
            os._exit(1)
        os._exit(0)  # deliberately bypass SQLite/Python cleanup
    pid, status = os.waitpid(child, 0)
    assert pid == child and os.waitstatus_to_exitcode(status) == 0
    with rs.Store(pin) as store:
        assert store.db.execute('SELECT state FROM operations').fetchall() == [('claimed',)]
        with pytest.raises(IdentityError, match='replay'):
            store.reserve(pin.principal, 'b'*64)


def test_foreign_file_owner_and_non_linux_backend_refuse(private_store, monkeypatch):
    pin, directory = private_store
    with rs.Store(pin): pass
    target = (directory / rs.NAME).stat()
    real = os.fstat
    def foreign(fd):
        meta = real(fd)
        if (meta.st_dev, meta.st_ino) == (target.st_dev, target.st_ino):
            fields = list(meta)
            fields[4] = os.geteuid() + 42
            return os.stat_result(fields)
        return meta
    monkeypatch.setattr(rs.os, 'fstat', foreign)
    with pytest.raises(IdentityError, match='private'):
        rs.Store(pin)
    monkeypatch.setattr(rs.sys, 'platform', 'darwin')
    with pytest.raises(IdentityError, match='Linux'):
        rs.Store(pin)
