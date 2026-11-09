"""Compare real CLI dry runs; no tracker, item or crew message is created."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

BASE = "6bb4694988539c60fbc1a4060a9ecb75fe9c8bcf"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    args = parser.parse_args()
    before = args.before.resolve()
    after = Path(__file__).resolve().parents[3]
    assert subprocess.check_output(["git", "-C", str(before), "rev-parse", "HEAD"], text=True).strip() == BASE
    for label, source, extra, expected in [
        ("before: required policy, missing deadline", before, [], 0),
        ("after: required policy, missing deadline", after, [], 1),
        ("after: explicit deadline", after, ["--due", "2026-12-01"], 0),
    ]:
        with TemporaryDirectory() as root:
            env = {k: v for k, v in os.environ.items() if not k.startswith("SHANTY_")}
            env.update(PYTHONPATH=str(source), SHANTY_TASK_DUE_REQUIRED="1")
            result = subprocess.run([
                sys.executable, "-c", "from shantytown.cli import main; raise SystemExit(main())",
                "--root", root, "task", "example work", "--dry-run", *extra,
            ], cwd=source, env=env, text=True, capture_output=True, timeout=30)
            print(label)
            print((result.stdout + result.stderr).strip())
            print("exit:", result.returncode)
            assert result.returncode == expected
            assert not (Path(root) / "items").exists()
    print("All three are dry runs; no tracker item, live message or deadline policy changed.")


if __name__ == "__main__":
    main()
