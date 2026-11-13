"""Atomic archive publication that preserves private relocated citations."""
import os
import hashlib
import re
from pathlib import Path
import shutil
import stat
import sys
import tempfile


def _private_digest(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_mode & 0o077 or before.st_nlink != 1):
            raise ValueError("refused non-private archive version")
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("archive version changed during read")
        return digest


def _origin(target):
    key = hashlib.sha256(target.name.encode()).hexdigest()
    return target.parent / ('.history-origin-' + key)


def _recaptured(path, target):
    match = re.fullmatch(re.escape(path.name) + r'\.recaptured-([0-9a-f]{12,64})', target.name)
    return match.group(1) if match else None


def _preserve(target, saved, expected):
    """Keep exact predecessor bytes, exclusively, before changing a citation."""
    try:
        if _private_digest(saved) != expected:
            raise ValueError("archive predecessor differs; retain it")
        return
    except FileNotFoundError:
        pass
    fd, temporary = tempfile.mkstemp(prefix='.history-save-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as outgoing:
            incoming_fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(incoming_fd, 'rb') as incoming:
                shutil.copyfileobj(incoming, outgoing)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if _private_digest(temporary) != expected:
            raise ValueError("archive predecessor changed; no publication")
        try:
            os.link(temporary, saved, follow_symlinks=False)
        except FileExistsError:
            if _private_digest(saved) != expected:
                raise ValueError("archive predecessor raced; retain it")
        Path(temporary).unlink()
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def destination(path):
    """Pin a relocated leaf; never follow an arbitrary writable symlink."""
    path = Path(path)
    if not path.is_symlink():
        return path, None
    link = os.readlink(path)
    target = path.resolve(strict=True)
    metadata, parent = target.stat(), target.parent.stat()
    suffix = _recaptured(path, target)
    if ((target.name != path.name and suffix is None) or target.parent.name != path.parent.name
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid() or parent.st_uid != os.getuid()
            or metadata.st_mode & 0o077 or parent.st_mode & 0o077
            or metadata.st_nlink != 1):
        raise ValueError(f"refused non-private or mismatched archive relocation: {path}")
    if suffix:
        # The suffix identifies the ORIGINAL bytes. Later natural scrubs must
        # keep the same citation, so retain that origin and every predecessor.
        origin = _origin(target)
        try:
            digest = _private_digest(origin)
        except FileNotFoundError:
            digest = _private_digest(target)
        if not digest.startswith(suffix):
            raise ValueError("recaptured archive digest does not match suffix")
    return target, link


def publish(path, writer):
    path = Path(path)
    target, link = destination(path)
    if link is not None and _recaptured(path, target):
        digest = _private_digest(target)
        origin = _origin(target)
        if not origin.exists():
            _preserve(target, origin, digest)
        _preserve(target, target.parent / ('.history-preserved-' + digest), digest)
    fd, temporary = tempfile.mkstemp(prefix='.history-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            writer(stream)
        # A retargeted citation must not redirect a publication already staged.
        current, current_link = destination(path)
        if current != target or current_link != link:
            raise ValueError(f"archive citation changed during publication: {path}")
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_write(path, data):
    publish(path, lambda stream: stream.write(data))


def copy_archive(source, path):
    target, _ = destination(path)
    if target.resolve() == Path(source).resolve():
        raise ValueError(f"refused capture destination pointing to source: {path}")
    def write(stream):
        with open(source, 'rb') as incoming:
            metadata = os.fstat(incoming.fileno())
            shutil.copyfileobj(incoming, stream)
            stream.flush()
            os.utime(stream.fileno(), ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    publish(path, write)


if __name__ == '__main__':
    try:
        copy_archive(sys.argv[1], sys.argv[2])
    except (OSError, ValueError) as error:
        print(f'FAILED archive publication: {error}', file=sys.stderr)
        sys.exit(1)
