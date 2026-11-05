"""Immutable local intents and verified receipts; no daemon or native rewrite.

A delivery invocation reads the original intent's remote receipt first, then
attempts at most one identical commit. Unknown outcomes retain the intent. A
later ordinary trigger can reconcile it; this function has no retry loop.
Local files are protected from accidental races, not from the same OS user.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .memory_files import SECURE_FDS, UnsafeMemory
from .memory_remote import Owner, Unproven, _json, canonical_intent

MAX_WIRE = 1024 * 1024
_NAME = re.compile(r'intent-([a-f0-9]{64})\.json\Z')
_DIRECTORY = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _version(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class Outbox:
    def __init__(self, root: Path, owner: Owner):
        self.root, self.owner = Path(root), owner

    def _open(self):
        if not SECURE_FDS:
            raise UnsafeMemory('secure outbox filesystem unavailable')
        fd = os.open(self.root, _DIRECTORY)
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            os.close(fd)
            raise UnsafeMemory('outbox directory must be private and user-owned')
        return fd

    @staticmethod
    def _read(fd, name):
        try:
            source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return None
        with os.fdopen(source, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or before.st_nlink != 1 or before.st_mode & 0o077 or before.st_size > MAX_WIRE):
                raise UnsafeMemory('unsafe outbox record')
            data = stream.read(MAX_WIRE + 1)
            after = os.fstat(stream.fileno())
        if len(data) > MAX_WIRE or _version(before) != _version(after):
            raise UnsafeMemory('outbox record changed or exceeds limit')
        return data

    def _install(self, fd, name, data):
        if len(data) > MAX_WIRE:
            raise UnsafeMemory('outbox record exceeds limit')
        try:
            target = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=fd)
        except FileExistsError:
            if self._read(fd, name) != data:
                raise UnsafeMemory('existing outbox record differs; preserve both intents')
            return
        with os.fdopen(target, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(fd)
        if self._read(fd, name) != data:
            raise UnsafeMemory('outbox durable readback differs')

    def enqueue(self, request):
        request = canonical_intent(request, self.owner)
        data = _bytes(request)
        name = 'intent-' + hashlib.sha256(data).hexdigest() + '.json'
        fd = self._open()
        try:
            self._install(fd, name, data)
        finally:
            os.close(fd)
        return name

    def _intent(self, fd, name, client):
        if not isinstance(name, str) or not _NAME.fullmatch(name) or client.owner != self.owner:
            raise Unproven('outbox name or selected owner mismatch')
        data = self._read(fd, name)
        if data is None or hashlib.sha256(data).hexdigest() != _NAME.fullmatch(name)[1]:
            raise Unproven('outbox intent is missing or changed')
        return canonical_intent(_json(data), self.owner)

    def accepted(self, name, client):
        """Verify a local receipt without network or freshness advancement."""
        fd = self._open()
        try:
            request = self._intent(fd, name, client)
            receipt_name = name.removesuffix('.json') + '.receipt.json'
            existing = self._read(fd, receipt_name)
            if existing is not None:
                return client._receipt(_json(existing), request)
            return None
        finally:
            os.close(fd)

    def deliver(self, name, client):
        accepted = self.accepted(name, client)
        if accepted is not None:
            return accepted
        fd = self._open()
        try:
            request = self._intent(fd, name, client)
            receipt_name = name.removesuffix('.json') + '.receipt.json'
            receipt = client.receipt(request)
            if receipt is None:
                receipt = client.commit(request)
            client._receipt({'receipt': receipt}, request)
            self._install(fd, receipt_name, _bytes({'receipt': receipt}))
            return receipt
        finally:
            os.close(fd)
