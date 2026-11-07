"""Atomic archive publication that preserves private relocated citations."""
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile


def destination(path):
    """Pin a relocated leaf; never follow an arbitrary writable symlink."""
    path = Path(path)
    if not path.is_symlink():
        return path, None
    link = os.readlink(path)
    target = path.resolve(strict=True)
    metadata, parent = target.stat(), target.parent.stat()
    if (target.name != path.name or target.parent.name != path.parent.name
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid() or parent.st_uid != os.getuid()
            or metadata.st_mode & 0o077 or parent.st_mode & 0o077
            or metadata.st_nlink != 1):
        raise ValueError(f"refused non-private or mismatched archive relocation: {path}")
    return target, link


def publish(path, writer):
    path = Path(path)
    target, link = destination(path)
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
