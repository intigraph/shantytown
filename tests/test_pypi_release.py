"""Exercise distribution identity and corruption refusal without any uploader."""
import hashlib
import io
from pathlib import Path
import runpy
import tarfile
import zipfile

import pytest

verify = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/verify-pypi-release.py'))['verify']


def release(root, metadata_version='0.6.0'):
    metadata = f'Name: shantytown\nVersion: {metadata_version}\n'
    wheel = root / 'shantytown-0.6.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('shantytown-0.6.0.dist-info/METADATA', metadata)
        archive.writestr('shantytown-0.6.0.dist-info/entry_points.txt',
                         '[console_scripts]\nst = shantytown.cli:main\n')
    source = root / 'shantytown-0.6.0.tar.gz'
    with tarfile.open(source, 'w:gz') as archive:
        info = tarfile.TarInfo('shantytown-0.6.0/PKG-INFO')
        body = metadata.encode()
        info.size = len(body)
        archive.addfile(info, io.BytesIO(body))
    manifest = root / 'SHA256SUMS'
    manifest.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n'
                                for p in (wheel, source)))
    return wheel, manifest


def test_valid_release_and_corrupted_wheel(tmp_path):
    wheel, _ = release(tmp_path)
    verify(tmp_path, 'v0.6.0')
    wheel.write_bytes(wheel.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='checksum mismatch'):
        verify(tmp_path, 'v0.6.0')


def test_matching_checksums_do_not_override_wrong_metadata(tmp_path):
    release(tmp_path, metadata_version='0.7.0')
    with pytest.raises(ValueError, match='identity'):
        verify(tmp_path, 'v0.6.0')


def test_path_traversal_and_duplicate_checksums_refused(tmp_path):
    _, manifest = release(tmp_path)
    original = manifest.read_text()
    manifest.write_text(original.replace('  shantytown', '  ../shantytown', 1))
    with pytest.raises(ValueError, match='unsafe'):
        verify(tmp_path, 'v0.6.0')
    manifest.write_text(original + original.splitlines()[0] + '\n')
    with pytest.raises(ValueError, match='duplicate'):
        verify(tmp_path, 'v0.6.0')


@pytest.mark.parametrize('tag', ['v0.6.1', 'v0.6.0rc1', 'main', '--help'])
def test_wrong_or_nonstable_tag_refused(tmp_path, tag):
    release(tmp_path)
    with pytest.raises(ValueError):
        verify(tmp_path, tag)
