"""Compare frozen base and candidate detector using the same native CLI fixture."""
import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[3]
BASE = "2bd929f85aaedc9afcb28ebdb0c9cc73e3bae1dc"
source = subprocess.check_output(["git", "show", BASE + ":shantytown/resume_kinds.py"], cwd=ROOT, text=True)
namespace = {}; exec(compile(source, "frozen-base", "exec"), namespace)
spec = importlib.util.spec_from_file_location("candidate", ROOT / "shantytown/resume_kinds.py")
candidate = importlib.util.module_from_spec(spec); spec.loader.exec_module(candidate)
def run(version):
    def invoke(argv):
        if argv != ["fixture-dp", "version"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="unknown flag")
        return SimpleNamespace(returncode=0, stdout="dp " + version, stderr="")
    return invoke
print("Target: source library; fixed native CLI fixture, no installed-state changes")
print("Base:", BASE, "Candidate behavior: 801b2b0d")
for version in ["0.12.1", "0.12.2"]:
    before = namespace["installed"]("dp>=0.12.2", run=run(version), which=lambda _:"fixture-dp")
    after = candidate.installed("dp>=0.12.2", run=run(version), which=lambda _:"fixture-dp")
    assert before[0] is None
    assert after[0] is (version == "0.12.2")
    print(version, "before:", before, "after:", after)
missing = candidate.installed("dp>=0.12.2", which=lambda _:None)
assert missing[0] is None
print("Missing binary remains UNKNOWN:", missing)
