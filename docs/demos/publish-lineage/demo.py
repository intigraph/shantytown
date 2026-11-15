"""Offline publish comparison. Requires the repository's pytest test fixtures."""
import importlib.util
import inspect
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from shantytown import pr_preflight as current
from test_pr_lineage import LineageForge
from test_pr_preflight import REPO, HEAD, BASE

BASE_REV = "4aa295157989aa734f0adaecdd2283f4408eeb41"


def probe(module):
    module.candidate = lambda *args: {"head": HEAD, "head_ref": "feature",
        "base": BASE, "base_ref": "main", "files": ["src/shared.py"]}
    forge = LineageForge()
    extra = {"patch_api": forge.patch} if "patch_api" in inspect.signature(module.run).parameters else {}
    result = module.run("unused", REPO, "main", "project-new",
        "Replacement\n\nSupersedes: #1", "Replacement", [],
        create=True, api=forge, **extra)
    return result["number"], forge.rows[0]["state"], len(forge.events)


with tempfile.TemporaryDirectory() as scratch:
    source = Path(scratch) / "before.py"
    source.write_bytes(subprocess.check_output([
        "git", "-C", str(ROOT), "show", BASE_REV + ":shantytown/pr_preflight.py"]))
    spec = importlib.util.spec_from_file_location("shantytown._lineage_before", source)
    before = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(before)
    print("Offline fake-forge probe; no network or live PR changes.")
    print("Input: same item project-new, Supersedes: #1, successor #99")
    print("BASE", BASE_REV, "successor/predecessor/writes:", probe(before))
    print("HEAD candidate successor/predecessor/writes:", probe(current))
    from shantytown.pr_lineage import declarations, LineageError
    try:
        declarations("Supersedes: https://example.org/pull/1")
    except LineageError as error:
        print("NEGATIVE malformed cross-repository reference:", error)
    else:
        raise AssertionError("invalid declaration accepted")
