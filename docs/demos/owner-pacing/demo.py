"""Compare actual administrator/owner routing on identical synthetic items."""
import argparse
from datetime import timedelta
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import shantytown.deferral_pacing as pacing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    fixtures = runpy.run_path(str(ROOT / "tests/test_deferral_owner_pacing.py"))
    source = subprocess.check_output(
        ["git", "show", f"{args.base}:shantytown/deferral_pacing.py"], text=True)
    baseline = {"__package__": "shantytown"}
    exec(compile(source, "baseline_deferral_pacing.py", "exec"), baseline)
    print(f"Synthetic source fixture; baseline {args.base}; candidate working tree")
    for label, implementation in [("before", baseline["OwnerPacing"]),
                                  ("after", pacing.OwnerPacing)]:
        with tempfile.TemporaryDirectory() as directory, patch.object(
                pacing, "OwnerPacing", implementation):
            item = fixtures["aged_row"](71)
            for hour in [71, 73, 73]:
                sent, admin, _ = fixtures["sweep"](
                    Path(directory), [item],
                    now=fixtures["NOW"] + timedelta(hours=hour - 71))
                print(f"{label}: lapse={hour}h owner={len(sent)} "
                      f"admin_digest={len(admin)} status={item['status']}")


if __name__ == "__main__":
    main()
