"""Compare source-only scrub accounting in isolated private fixtures."""
import argparse
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
import test_scrub_producer_coverage as fixture

parser = argparse.ArgumentParser()
parser.add_argument("--base-script", type=Path, required=True)
parser.add_argument("--head-script", type=Path, required=True)
args = parser.parse_args()
for label, script in (("base", args.base_script), ("candidate", args.head_script)):
    fixture.SCRIPT = script.resolve()
    case = fixture.LegacyProducerCoverage()
    case.setUp()
    try:
        before = case.sweep()
        shutil.rmtree(case.root)
        after = case.sweep(check=True)
        print(f"{label}: producer cleanup: persistent {before['scrub_guard_persistent_repos_total']} -> {after['scrub_guard_persistent_repos_total']}; missing {after['scrub_guard_missing_total']}", flush=True)
        shutil.rmtree(case.real)
        removed = case.sweep(check=True)
        print(f"{label}: real repository removal: persistent {after['scrub_guard_persistent_repos_total']} -> {removed['scrub_guard_persistent_repos_total']}", flush=True)
    finally:
        case.doCleanups()
