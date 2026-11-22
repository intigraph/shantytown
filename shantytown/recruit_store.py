"""Private Linux controller state. Provisioning and activation are separate.

No caller or signed request chooses a state path. The protected controller
binding supplies its root, and this module opens one fixed private directory.
No pruning, database replacement, repair or replay is automatic.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

from .actor_identity import IdentityError
from .recruit_request import message

NAME = 'requests.sqlite3'
MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 50000
SCHEMA = (
    'CREATE TABLE nonces (principal TEXT NOT NULL, nonce TEXT NOT NULL, PRIMARY KEY(principal,nonce)) WITHOUT ROWID',
    'CREATE TABLE audit (principal TEXT NOT NULL, nonce TEXT, outcome TEXT NOT NULL, reason TEXT NOT NULL)',
    'CREATE TABLE operations (id TEXT PRIMARY KEY, principal TEXT NOT NULL, nonce TEXT NOT NULL, repo TEXT NOT NULL, pr INTEGER NOT NULL, head TEXT NOT NULL, job TEXT NOT NULL, verb TEXT NOT NULL, target TEXT, state TEXT NOT NULL, plan_digest TEXT) WITHOUT ROWID',
    "CREATE UNIQUE INDEX launch_once ON operations(repo,pr,head,job) WHERE verb='launch'",
)


def _directory(path, owner):
    """Walk using directory FDs, refusing links and mutable/foreign ancestors."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise IdentityError('controller state needs an absolute protected root')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=fd)
            os.close(fd)
            fd = child
            meta = os.fstat(fd)
            if meta.st_uid not in (0, owner) or meta.st_mode & 0o022:
                raise IdentityError('controller state has mutable or foreign ancestry')
        meta = os.fstat(fd)
        if meta.st_uid != owner or stat.S_IMODE(meta.st_mode) != 0o700:
            raise IdentityError('controller state directory must be private and controller-owned')
        return fd
    except BaseException:
        os.close(fd)
        raise


def _file(meta, owner):
    if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != owner
            or stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_nlink != 1
            or meta.st_size > MAX_BYTES):
        raise IdentityError('controller state file is not private single-link regular data')


class Store:
    """Fixed-path durable ledger, bound to the loaded recruiter principal.

    Lower-privilege users cannot change any component. Linux's directory-FD
    path pins SQLite and its journal to the validated directory inode. The lock
    serializes initialization only; SQLite transactions own nonce uniqueness.
    """
    def __init__(self, binding):
        self.db = None
        self.directory = None
        if (not sys.platform.startswith('linux') or not isinstance(binding.root, str)
                or not isinstance(binding.principal, str) or not binding.principal
                or os.geteuid() == binding.uid):
            raise IdentityError('independent Linux controller state identity required')
        self.principal = binding.principal
        owner = os.geteuid()
        self.directory = _directory(Path(binding.root) / 'ephemeral' / 'recruitment', owner)
        lock = None
        try:
            lock = os.open('.requests.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW |
                           os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=self.directory)
            _file(os.fstat(lock), owner)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for name in os.listdir(self.directory):
                if name not in ('.requests.lock', NAME, NAME + '-journal'):
                    raise IdentityError('unexpected controller state entry')
                _file(os.stat(name, dir_fd=self.directory, follow_symlinks=False), owner)
            created = False
            try:
                dbfd = os.open(NAME, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW |
                               os.O_CLOEXEC, 0o600, dir_fd=self.directory)
                created = True
            except FileExistsError:
                dbfd = os.open(NAME, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK |
                               os.O_CLOEXEC, dir_fd=self.directory)
            try:
                meta = os.fstat(dbfd)
                _file(meta, owner)
                if not created and meta.st_size == 0:
                    raise IdentityError('incomplete controller state requires operator disposition')
            finally:
                os.close(dbfd)
            self.db = sqlite3.connect(f'file:/proc/self/fd/{self.directory}/{NAME}?mode=rw',
                                      uri=True, isolation_level=None, timeout=3)
            self.db.execute('PRAGMA trusted_schema=OFF')
            self.db.execute('PRAGMA journal_mode=DELETE')
            # EXTRA also syncs the directory after DELETE-journal removal.
            self.db.execute('PRAGMA synchronous=EXTRA')
            self.db.execute('PRAGMA temp_store=MEMORY')
            if self.db.execute('PRAGMA page_size').fetchone()[0] != 4096:
                raise IdentityError('controller state page size unproved')
            self.db.execute('PRAGMA max_page_count=16384')
            if created:
                with self.transaction():
                    for sql in SCHEMA:
                        self.db.execute(sql)
                    self.db.execute('PRAGMA user_version=1')
                os.fsync(self.directory)
            expected = set(SCHEMA)
            actual = {sql for sql, in self.db.execute(
                'SELECT sql FROM sqlite_master WHERE sql IS NOT NULL')}
            if (self.db.execute('PRAGMA user_version').fetchone()[0] != 1 or actual != expected
                    or self.db.execute('PRAGMA quick_check(1)').fetchone()[0] != 'ok'):
                raise IdentityError('controller state schema/integrity unproved')
        except BaseException:
            self.close()
            raise
        finally:
            if lock is not None:
                os.close(lock)

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def reserve(self, principal, nonce):
        if (principal != self.principal or not isinstance(nonce, str)
                or not re.fullmatch('[0-9a-f]{64}', nonce)):
            raise IdentityError('controller nonce identity refused')
        try:
            with self.transaction():
                if self.db.execute('SELECT count(*) FROM nonces').fetchone()[0] >= MAX_ROWS:
                    raise IdentityError('controller nonce capacity reached; retain state')
                self.db.execute('INSERT INTO nonces VALUES (?,?)', (principal, nonce))
        except sqlite3.IntegrityError as error:
            raise IdentityError('recruitment replay refused') from error

    def record(self, nonce, outcome, reason):
        if (outcome not in ('qualified', 'refused') or not isinstance(reason, str)
                or not re.fullmatch('[a-z-]{1,64}', reason)):
            raise IdentityError('controller audit label refused')
        with self.transaction():
            if self.db.execute('SELECT count(*) FROM audit').fetchone()[0] >= MAX_ROWS * 4:
                raise IdentityError('controller audit capacity reached; retain state')
            self.db.execute('INSERT INTO audit VALUES (?,?,?,?)',
                            (self.principal, nonce, outcome, reason))

    def claim(self, body):
        """Commit one candidate before planner/launcher admission or lost reply."""
        operation = hashlib.sha256(message(body)).hexdigest()
        try:
            with self.transaction():
                if body['principal'] != self.principal or self.db.execute(
                        'SELECT 1 FROM nonces WHERE principal=? AND nonce=?',
                        (self.principal, body['nonce'])).fetchone() is None:
                    raise IdentityError('handoff nonce was not reserved')
                if self.db.execute('SELECT count(*) FROM operations').fetchone()[0] >= MAX_ROWS:
                    raise IdentityError('controller operation capacity reached; retain state')
                self.db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                                (operation, self.principal, body['nonce'], body['repo'], body['pr'],
                                 body['head'], body['job'], body['verb'], body['target'], 'claimed', None))
        except sqlite3.IntegrityError as error:
            raise IdentityError('controller handoff already claimed') from error
        return operation

    def finish(self, operation, *, prepared=False, plan_digest=None):
        if prepared and (not isinstance(plan_digest, str) or not re.fullmatch('[0-9a-f]{64}', plan_digest)):
            raise IdentityError('controller plan digest refused')
        with self.transaction():
            changed = self.db.execute(
                "UPDATE operations SET state=?,plan_digest=? WHERE id=? AND principal=? AND state='claimed'",
                ('prepared' if prepared else 'refused', plan_digest, operation, self.principal)).rowcount
            if changed != 1:
                raise IdentityError('controller handoff terminal or unknown')

    def finish_execution(self, operation, *, state, job_digest=None):
        """Retain the result of one controller launch attempt; never rearm it."""
        if state not in ('launched', 'refused', 'unknown'):
            raise IdentityError('controller execution outcome refused')
        if state == 'launched' and (not isinstance(job_digest, str)
                                   or not re.fullmatch('[0-9a-f]{64}', job_digest)):
            raise IdentityError('controller execution digest refused')
        with self.transaction():
            changed = self.db.execute(
                "UPDATE operations SET state=?,plan_digest=? WHERE id=? AND principal=? AND state='claimed'",
                (state, job_digest, operation, self.principal)).rowcount
            if changed != 1:
                raise IdentityError('controller execution terminal or unknown')

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self.directory is not None:
            os.close(self.directory)
            self.directory = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
