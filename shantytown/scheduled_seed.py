"""Create/read one keyed seed before normal assignment; never retry uncertainty.

Library only. A trusted signed receiver supplies an admitted firing/run identity
and fixed policy. This module starts no consumer and authenticates no delivery.
"""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat


class SeedUnknown(RuntimeError):
    """The durable claim survives; no second create or assignment is permitted."""


@dataclass(frozen=True)
class SeedRequest:
    job: str
    run_iri: str
    scheduled_at: int
    due_at: int
    recipient: str
    title: str
    body: str

    @property
    def firing(self):
        # Stable across recipe revisions: a preserved ledger refuses a changed
        # policy for a slot instead of minting a second agent task.
        raw = json.dumps({'job': self.job, 'scheduled_at': self.scheduled_at},
                         sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        return 'scheduled-agent-v1-'+hashlib.sha256(raw).hexdigest()

    def fields(self):
        for value in (self.job, self.run_iri):
            if (type(value) is not str or len(value) > 4096 or
                    not re.fullmatch(r'[A-Za-z][A-Za-z0-9+.-]*:[^\s<>"{}|^`\\]+', value)):
                raise ValueError('admitted absolute job/firing/run identities required')
        if (type(self.scheduled_at) is not int or type(self.due_at) is not int or
                not 0 <= self.scheduled_at < self.due_at <= 253402300799):
            raise ValueError('bounded UTC slot and later completion deadline required')
        # Validate the existing canonical Chaski protocol; this is identity
        # consistency, not proof of signing/eligibility or executable admission.
        try:
            prefix, encoded = self.run_iri.rsplit('run:scheduled-v1-', 1)
            raw = base64.b64decode(encoded+'='*(-len(encoded)%4), altchars=b'-_', validate=True)
            binding = json.loads(raw)
            expected = {'job','revision','host','manifest_sha256','agent','workflow','scheduled_at','version'}
            if (not prefix or type(binding) is not dict or set(binding) != expected or
                    type(binding['version']) is not int or binding['version'] != 1 or
                    type(binding['scheduled_at']) is not int or binding['scheduled_at'] != self.scheduled_at or
                    binding['job'] != self.job or
                    any(type(binding[k]) is not str or not 0 < len(binding[k]) <= 2048
                        for k in expected - {'scheduled_at','version'}) or
                    not re.fullmatch('[0-9a-f]{64}', binding['manifest_sha256']) or
                    base64.urlsafe_b64encode(json.dumps(binding,sort_keys=True,
                        separators=(',', ':')).encode()).decode().rstrip('=') != encoded):
                raise ValueError('noncanonical firing binding')
        except (ValueError, TypeError, UnicodeError):
            raise ValueError('exact canonical signed-run identity required') from None
        if (type(self.recipient) is not str or
                not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', self.recipient)):
            raise ValueError('fixed recipient required')
        if (type(self.title) is not str or not self.title.strip() or len(self.title) > 256 or
                type(self.body) is not str or len(self.body.encode('utf-8')) > 16000):
            raise ValueError('bounded fixed task content required')
        return dict(title=self.title, description=f'Job: {self.job}\nFiring: {self.firing}\n\n{self.body}',
                    workflow_run=self.run_iri, step='agent-task', visit=1,
                    external_ref=self.firing, due=datetime.fromtimestamp(
                        self.due_at, timezone.utc).isoformat().replace('+00:00', 'Z'))


class NativeSeedPort:
    """Existing proven Seeds adapter and the normal ST go parser; no new transport."""
    def __init__(self, tracker, command):
        from .sd import SdTracker
        if not isinstance(tracker, SdTracker):
            raise ValueError('a proven Seeds adapter is required, not a fallback tracker')
        self.tracker, self.command = tracker, command
        self.scope = json.dumps(asdict(tracker.prove_store()), sort_keys=True)

    def create(self, fields):
        return self.tracker.create(**fields).id

    def read(self, item):
        if type(item) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', item):
            raise SeedUnknown('exact seed ID required')
        result = self.tracker._bd('show', item, '--json')
        if result.returncode:
            raise SeedUnknown('exact seed readback unavailable')
        value = json.loads(result.stdout)
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
        if type(value) is not dict or value.get('id') != item:
            raise SeedUnknown('exact seed readback unavailable')
        return value

    def assign(self, item, request):
        # command is the fixed normal CLI invocation seam with deployment root,
        # registry and backend already pinned by its runtime owner.
        return self.command(['go', item, request.recipient, '--quipu-node', request.job,
                             '--note', 'scheduled firing: '+request.firing])


class SeedLedger:
    def __init__(self, path):
        path = Path(path)
        if not path.is_absolute() or not path.parent.is_dir():
            raise ValueError('absolute provisioned ledger path required')
        parent = path.parent.stat()
        if parent.st_uid != os.getuid() or parent.st_mode & 0o022:
            raise ValueError('owned ledger directory required')
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    info.st_mode & 0o022 or info.st_nlink != 1):
                raise ValueError('owned regular ledger required')
        else:
            os.close(fd)
        self.conn = sqlite3.connect(path, isolation_level=None)
        tables = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if tables - {'scheduled_seed_claims'}:
            self.conn.close()
            raise ValueError('dedicated execution ledger required; never a board database')
        self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.execute('CREATE TABLE IF NOT EXISTS scheduled_seed_claims ('
            'firing TEXT PRIMARY KEY, digest TEXT NOT NULL, state TEXT NOT NULL, seed TEXT)')

    def close(self):
        self.conn.close()

    def _identity(self, request, port):
        fields = request.fields()
        raw = json.dumps({'request': asdict(request), 'store': port.scope},
                         sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        return fields, hashlib.sha256(raw).hexdigest()

    def _verify(self, seed, item, fields):
        if (type(seed) is not dict or seed.get('id') != item or
                any(seed.get(key) != fields[field] for key, field in
                    [('title','title'), ('description','description'), ('workflow_run','workflow_run'),
                     ('external_ref','external_ref'), ('due_at','due')]) or
                seed.get('status') != 'open' or seed.get('assignee') is not None):
            raise SeedUnknown('created seed scope or unassigned/open state not verified')

    def deliver(self, request: SeedRequest, port):
        fields, digest = self._identity(request, port)
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            row = self.conn.execute('SELECT digest,state,seed FROM scheduled_seed_claims WHERE firing=?',
                                    (request.firing,)).fetchone()
            if row is None:
                self.conn.execute('INSERT INTO scheduled_seed_claims VALUES (?,?,?,NULL)',
                                  (request.firing, digest, 'creating'))
            elif row[0] != digest:
                raise ValueError('firing identity reused with changed policy/store')
            self.conn.execute('COMMIT')
        except BaseException:
            self.conn.execute('ROLLBACK')
            raise
        if row is None:
            try:
                item = port.create(fields)
                if not isinstance(item, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', item):
                    raise SeedUnknown('create receipt has no exact ID')
                self._verify(port.read(item), item, fields)
            except Exception:
                raise SeedUnknown('seed creation/readback uncertain; no create retry or assignment') from None
            bound = self.conn.execute('UPDATE scheduled_seed_claims SET state=?,seed=? '
                'WHERE firing=? AND digest=? AND state=?',
                ('seeded', item, request.firing, digest, 'creating'))
            if bound.rowcount != 1:
                raise SeedUnknown('creation was already reconciled; do not overwrite assignment claim')
        else:
            _, state, item = row
            if state in ('delivered', 'refused'):
                return {'seed': item, 'assignment': state}
            if state != 'seeded':
                raise SeedUnknown('claimed operation uncertain; reconcile instead of repeating')
            self._verify(port.read(item), item, fields)
        # Compare-and-swap before the one-way call also serializes two processes
        # resuming a verified seed. A crash here leaves assignment UNKNOWN.
        claim = self.conn.execute('UPDATE scheduled_seed_claims SET state=? WHERE firing=? AND state=?',
                                  ('assigning', request.firing, 'seeded'))
        if claim.rowcount != 1:
            raise SeedUnknown('assignment already claimed')
        try:
            code = port.assign(item, request)
        except Exception:
            raise SeedUnknown('assignment uncertain; do not repeat') from None
        if type(code) is not int or code not in (0, 1):
            raise SeedUnknown('assignment uncertain; do not repeat')
        state = 'delivered' if code == 0 else 'refused'
        self.conn.execute('UPDATE scheduled_seed_claims SET state=? WHERE firing=?',
                          (state, request.firing))
        return {'seed': item, 'assignment': state}

    def reconcile_created(self, request, item, port):
        """Owner-supplied exact ID/readback only; never guesses or creates again."""
        fields, digest = self._identity(request, port)
        self._verify(port.read(item), item, fields)
        changed = self.conn.execute('UPDATE scheduled_seed_claims SET seed=?,state=? '
            'WHERE firing=? AND digest=? AND state=?',
            (item, 'seeded', request.firing, digest, 'creating'))
        if changed.rowcount != 1:
            raise SeedUnknown('no matching uncertain creation to reconcile')

    def for_code_outcome(self, request, port, outcome):
        """A trusted actual code-job outcome mints work only on failure.

        The existing Shuttle port owns its signed run/publication independently.
        This is not an alternate execution or run-recording path.
        """
        if (type(outcome) is not dict or set(outcome) != {'outcome','exit_code'} or
                type(outcome['exit_code']) is not int or not 0 <= outcome['exit_code'] <= 255 or
                outcome['outcome'] not in ('succeeded','failed','skipped-by-hold') or
                (outcome['outcome'] == 'failed') != (outcome['exit_code'] != 0)):
            raise ValueError('actual consistent code-job outcome required')
        return self.deliver(request, port) if outcome['outcome'] == 'failed' else None
