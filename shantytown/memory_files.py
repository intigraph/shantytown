"""Lossless bounded memory snapshots and non-destructive generation staging.

This is file transport, not an owner authenticator or a native harness adapter.
In particular, a launch lock cannot exclude an external editor. Never replace a
live memory root here: callers may select a new generation only through an
independently verified harness handoff. Failed generations are not selected.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import secrets
import stat

MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_FILES = 128
MAX_ENTRIES = 160
MAX_DEPTH = 8
SECURE_FDS = (hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW")
              and os.open in os.supports_dir_fd and os.scandir in os.supports_fd)
_DIRECTORY = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


class UnsafeMemory(ValueError):
    """Coverage is unproven; preserve the existing files rather than guessing."""


def _path(value: str) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise UnsafeMemory("memory path is not text")
    path = PurePosixPath(value)
    parts = value.split("/")
    if (not value or path.is_absolute() or len(parts) > MAX_DEPTH
            or any(p in {"", ".", ".."} or "\\" in p or "\x00" in p for p in parts)
            or len(value.encode("utf-8")) > 1024):
        raise UnsafeMemory("invalid relative memory path")
    return tuple(parts)


def _version(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_nlink)


@dataclass(frozen=True)
class MemoryFile:
    path: str
    data: bytes

    def __post_init__(self):
        _path(self.path)
        if type(self.data) is not bytes:
            raise UnsafeMemory("memory content is not immutable bytes")
        if len(self.data) > MAX_FILE_BYTES:
            raise UnsafeMemory("memory file exceeds byte limit")
        try:
            self.data.decode("utf-8")
        except UnicodeError as error:
            raise UnsafeMemory("memory file is not UTF-8") from error

    @property
    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()


def validate(files: tuple[MemoryFile, ...]) -> None:
    paths = [f.path for f in files]
    if len(files) > MAX_FILES or sum(len(f.data) for f in files) > MAX_TOTAL_BYTES:
        raise UnsafeMemory("memory snapshot exceeds limit")
    if len(set(paths)) != len(paths):
        raise UnsafeMemory("duplicate memory path")
    for path in paths:
        parts = _path(path)
        if any("/".join(parts[:n]) in paths for n in range(1, len(parts))):
            raise UnsafeMemory("file is also a directory")


def snapshot(root: Path) -> tuple[MemoryFile, ...]:
    """Read regular single-link files under an adapter-selected root, no links.

    Before/after directory and file checks detect observed concurrent changes;
    this is not an atomic multi-file snapshot against noncooperating writers.
    A durable commit still needs the separate owner/file revision CAS.
    """
    if not SECURE_FDS:
        raise UnsafeMemory("filesystem lacks secure descriptor operations")
    result = []
    entries_seen = 0
    total = 0

    def walk(fd, prefix=()):
        nonlocal entries_seen, total
        before = _version(os.fstat(fd))
        with os.scandir(fd) as entries:
            for entry in entries:
                entries_seen += 1
                if entries_seen > MAX_ENTRIES:
                    raise UnsafeMemory("memory tree exceeds entry limit")
                parts = (*prefix, entry.name)
                name = "/".join(parts)
                _path(name)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(entry.name, _DIRECTORY, dir_fd=fd)
                    try:
                        if _version(os.fstat(child)) != _version(info):
                            raise UnsafeMemory("memory directory changed")
                        walk(child, parts)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    child = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                    dir_fd=fd)
                    try:
                        opened = os.fstat(child)
                        if (_version(opened) != _version(info)
                                or not stat.S_ISREG(opened.st_mode)):
                            raise UnsafeMemory("memory file changed")
                        with os.fdopen(os.dup(child), "rb") as stream:
                            data = stream.read(MAX_FILE_BYTES + 1)
                        if _version(os.fstat(child)) != _version(opened):
                            raise UnsafeMemory("memory file changed during read")
                        result.append(MemoryFile(name, data))
                        total += len(data)
                        if len(result) > MAX_FILES or total > MAX_TOTAL_BYTES:
                            raise UnsafeMemory("memory snapshot exceeds limit")
                    finally:
                        os.close(child)
                else:
                    raise UnsafeMemory("memory contains link or non-regular entry")
        if _version(os.fstat(fd)) != before:
            raise UnsafeMemory("memory directory changed during read")

    try:
        fd = os.open(root, _DIRECTORY)
        try:
            walk(fd)
        finally:
            os.close(fd)
    except OSError as error:
        # Error messages never echo file contents or paths into public logs.
        raise UnsafeMemory("memory tree unreadable or changed") from error
    files = tuple(sorted(result, key=lambda f: f.path))
    validate(files)
    return files


def stage(files: tuple[MemoryFile, ...], parent: Path) -> Path:
    """Create a fresh generation. Never overwrite, remove or select live files.

    A failed generation is retained for inspection/recovery. No manifest claims
    completeness unless the caller receives this function's validated return.
    Parent must be a trusted existing staging directory, not a native root.
    """
    validate(files)
    if not SECURE_FDS:
        raise UnsafeMemory("filesystem lacks secure descriptor operations")
    # A held descriptor keeps parent-path replacements from redirecting writes.
    try:
        parent_fd = os.open(parent, _DIRECTORY)
    except OSError as error:
        raise UnsafeMemory("generation parent is not a regular directory") from error
    name = "memory-generation-" + secrets.token_hex(16)
    generation = parent / name
    root_fd = None
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        root_fd = os.open(name, _DIRECTORY, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except BaseException:
        if root_fd is not None:
            os.close(root_fd)
        raise
    finally:
        os.close(parent_fd)
    try:
        for file in files:
            parts = _path(file.path)
            fd = os.dup(root_fd)
            try:
                for part in parts[:-1]:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                    child = os.open(part, _DIRECTORY, dir_fd=fd)
                    os.close(fd)
                    fd = child
                target = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                with os.fdopen(target, "wb") as stream:
                    stream.write(file.data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fsync(fd)
            finally:
                os.close(fd)
        os.fsync(root_fd)
    finally:
        os.close(root_fd)
    if snapshot(generation) != tuple(sorted(files, key=lambda f: f.path)):
        raise UnsafeMemory("staged generation readback differs")
    return generation
