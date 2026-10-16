"""Exercise the exact-ID failure path, without HTTP or a real tracker."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from shantytown import br

BASE = "6b0083f69f505421bc8434056735a82265ddb962"


class Tracker:
    repo = "fixture"
    repos = ["fixture"]

    def __init__(self):
        self.calls = []

    def _bd(self, *args):
        self.calls.append(list(args))
        return subprocess.CompletedProcess(args, 2, "", "HTTP408 fixture unavailable")


def run(module):
    tracker = Tracker()
    try:
        module.show(tracker, "test-exact")
    except RuntimeError as error:
        message = str(error)
    else:
        raise AssertionError("unavailable read incorrectly succeeded")
    return {"sdk_calls": len(tracker.calls), "commands": tracker.calls, "error": message}


with tempfile.TemporaryDirectory(prefix="show-failure-") as temp:
    path = Path(temp) / "baseline.py"
    path.write_bytes(subprocess.check_output(["git", "show", BASE + ":shantytown/br.py"]))
    spec = importlib.util.spec_from_file_location("shantytown._show_failure_baseline", path)
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    before, after = run(old), run(br)
    assert before["sdk_calls"] == 2 and after["sdk_calls"] == 1
    assert before["error"] == after["error"]
    print(json.dumps({"before": before, "after": after,
        "scope": "injected SDK failure, real show handler; no HTTP; production per-command query cost unmeasured"}, indent=2))
