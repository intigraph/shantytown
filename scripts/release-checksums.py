#!/usr/bin/env python3
"""Write checksums only for one matching Shantytown wheel/source pair."""
# arming: ci Release workflow after build and before installed-wheel proof
from email.parser import BytesParser
import hashlib
from pathlib import Path
import sys
import tarfile
import zipfile


def metadata(data):
    fields = BytesParser().parsebytes(data)
    if fields["Name"] != "shantytown" or not fields["Version"]:
        raise ValueError("artifact must declare Shantytown name and version")
    return fields["Version"]


def generate(directory):
    directory = Path(directory)
    entries = list(directory.iterdir())
    wheels = [p for p in entries if p.name.endswith(".whl")]
    sources = [p for p in entries if p.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sources) != 1 or len(entries) != 2:
        raise ValueError("require exactly one wheel and one source archive, no extra entries")
    for path in entries:
        if path.is_symlink() or not path.is_file():
            raise ValueError("release artifacts must be regular files")
        if any(char.isspace() for char in path.name):
            raise ValueError("release artifact filenames cannot contain whitespace")
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ValueError("wheel must have exactly one package metadata entry")
        version = metadata(wheel.read(names[0]))
    with tarfile.open(sources[0], "r:gz") as source:
        infos = [m for m in source.getmembers() if len(Path(m.name).parts) == 2 and m.name.endswith("/PKG-INFO") and m.isfile()]
        if len(infos) != 1:
            raise ValueError("source archive must have one root package metadata entry")
        if metadata(source.extractfile(infos[0]).read()) != version:
            raise ValueError("wheel and source archive versions disagree")
    if wheels[0].name != f"shantytown-{version}-py3-none-any.whl" or sources[0].name != f"shantytown-{version}.tar.gz":
        raise ValueError("artifact filenames disagree with package metadata")
    lines = [hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in sorted(entries)]
    output = directory / "SHA256SUMS"
    with output.open("x") as stream:
        stream.writelines(lines)
    return output


if __name__ == "__main__":
    try:
        print(generate(sys.argv[1]))
    except (ValueError, OSError, IndexError, zipfile.BadZipFile, tarfile.TarError) as error:
        sys.exit("checksum publication refused: " + str(error))
