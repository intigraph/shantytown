"""Release manifests must select one real, matching artifact pair."""
import hashlib
import io
from pathlib import Path
import runpy
import subprocess
import tarfile
import zipfile

import pytest

generate = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/release-checksums.py"))["generate"]


def pair(root, source_version="0.4.0"):
    wheel = root / "shantytown-0.4.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("shantytown-0.4.0.dist-info/METADATA", "Name: shantytown\nVersion: 0.4.0\n")
    source = root / f"shantytown-{source_version}.tar.gz"
    data = f"Name: shantytown\nVersion: {source_version}\n".encode()
    with tarfile.open(source, "w:gz") as archive:
        entry = tarfile.TarInfo(f"shantytown-{source_version}/PKG-INFO")
        entry.size = len(data)
        archive.addfile(entry, io.BytesIO(data))
    return wheel, source


def test_real_checksum_pair_tamper_and_missing_file(tmp_path):
    wheel, source = pair(tmp_path)
    manifest = generate(tmp_path)
    expected = "".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n" for p in sorted([wheel, source]))
    assert manifest.read_text() == expected
    assert sum(line.endswith(".whl") for line in manifest.read_text().splitlines()) == 1
    check = lambda: subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=tmp_path, capture_output=True).returncode
    assert check() == 0
    wheel.write_bytes(wheel.read_bytes() + b"tamper")
    assert check() != 0
    wheel.unlink()
    assert check() != 0


@pytest.mark.parametrize("failure", ["missing", "duplicate", "extra", "symlink", "directory", "filename", "metadata", "versions"])
def test_bad_artifact_sets_refuse_without_manifest(tmp_path, failure):
    wheel, source = pair(tmp_path, "0.5.0" if failure == "versions" else "0.4.0")
    if failure == "missing":
        source.unlink()
    elif failure == "duplicate":
        (tmp_path / "other.whl").write_bytes(wheel.read_bytes())
    elif failure == "extra":
        (tmp_path / "keep.txt").write_text("retained")
    elif failure == "symlink":
        wheel.unlink()
        wheel.symlink_to(source)
    elif failure == "directory":
        wheel.unlink()
        wheel.mkdir()
    elif failure == "filename":
        wheel.rename(tmp_path / "other.whl")
    elif failure == "metadata":
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("other.dist-info/METADATA", "Name: other\nVersion: 0.4.0\n")
    with pytest.raises(ValueError):
        generate(tmp_path)
    assert not (tmp_path / "SHA256SUMS").exists()


def test_existing_manifest_is_preserved(tmp_path):
    pair(tmp_path)
    manifest = generate(tmp_path)
    original = manifest.read_bytes()
    with pytest.raises(ValueError):
        generate(tmp_path)
    assert manifest.read_bytes() == original
