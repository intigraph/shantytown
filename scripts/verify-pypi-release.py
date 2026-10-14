#!/usr/bin/env python3
"""Validate the exact public release pair before an OIDC publishing job."""
import email
import hashlib
from pathlib import Path
import re
import sys
import tarfile
import zipfile


def verify(root: Path, tag: str) -> None:
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag):
        raise ValueError('Only stable vMAJOR.MINOR.PATCH releases can be published')
    version = tag[1:]
    expected = {f'shantytown-{version}-py3-none-any.whl', f'shantytown-{version}.tar.gz'}
    hashes = {}
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)', line)
        if not match or match[2] in hashes:
            raise ValueError('Malformed, duplicate or unsafe checksum entry')
        hashes[match[2]] = match[1]
    if set(hashes) != expected or {p.name for p in root.iterdir()} != expected | {'SHA256SUMS'}:
        raise ValueError('Release must contain exactly the expected wheel, sdist and checksum manifest')
    for name, digest in hashes.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Release checksum mismatch')
    wheel = root / f'shantytown-{version}-py3-none-any.whl'
    with zipfile.ZipFile(wheel) as archive:
        metadata = archive.read(f'shantytown-{version}.dist-info/METADATA').decode()
        entry = archive.read(f'shantytown-{version}.dist-info/entry_points.txt').decode()
        if not re.search(r'^st\s*=\s*shantytown\.cli:main\s*$', entry, re.M):
            raise ValueError('Wheel lacks the expected st console entry point')
    with tarfile.open(root / f'shantytown-{version}.tar.gz') as archive:
        member = archive.getmember(f'shantytown-{version}/PKG-INFO')
        if not member.isfile():
            raise ValueError('sdist metadata is not a regular file')
        stream = archive.extractfile(member)
        assert stream is not None
        with stream:
            source_metadata = stream.read().decode()
    for content in (metadata, source_metadata):
        message = email.message_from_string(content)
        if message['Name'] != 'shantytown' or message['Version'] != version:
            raise ValueError('Distribution identity disagrees with release tag')
        if message.get_all('Requires-Dist'):
            raise ValueError('Unexpected runtime dependencies; review before publishing')
    print(f'Verified shantytown {version}: wheel, sdist, checksums and console entry point')


if __name__ == '__main__':
    try:
        verify(Path(sys.argv[1]), sys.argv[2])
    except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile) as error:
        sys.exit(str(error))
