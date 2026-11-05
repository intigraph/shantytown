#!/usr/bin/env python3
"""Offline library demonstration; no native engine or publisher invocation."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
BASE = "4c3d91b9941153c079c461f08590917c542b22e2"
SOURCE = "3ad7c45"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


with tempfile.TemporaryDirectory() as directory:
    old = Path(directory) / "base-publisher.py"
    old.write_bytes(subprocess.check_output(
        ["git", "show", BASE + ":scripts/publish_repository_share.py"], cwd=ROOT))
    before = load("base_publisher", old)
    fixture = load("candidate_controls", ROOT / "scripts/test-repository-share-publication.py")
    case = fixture.Publication()
    case.setUp()
    try:
        carrier = case.add_alignment()
        print("Target: source helpers and disposable synthetic envelope; no native engine")
        print("Base:", BASE, "candidate helper source:", SOURCE)
        print("Same reviewed carrier: bytes", len(carrier), "SHA256", hashlib.sha256(carrier).hexdigest())
        try:
            before.package(case.stage, case.archive)
        except ValueError as error:
            print("BEFORE exact carrier package: REFUSED:", error)
        else:
            raise AssertionError("base unexpectedly accepted the carrier")
        assert not case.archive.exists()
        case.prepare()
        fixture.verifier.verify(case.root, "v1.2.3", case.revision)
        print("AFTER exact carrier package + independent readback: PASS")
        (case.stage / "alignments.ttl").write_bytes(carrier + b"# modified\n")
        try:
            fixture.publisher.check_share(case.stage)
        except ValueError as error:
            print("CONTROL modified carrier: REFUSED:", error)
        else:
            raise AssertionError("candidate accepted modified carrier")
    finally:
        case.doCleanups()
