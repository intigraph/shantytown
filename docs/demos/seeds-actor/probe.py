"""Compare the same isolated child-tool actor probe before and after the fix."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    archive = subprocess.check_output(
        ["git", "-C", str(root), "archive", args.base, "shantytown"])
    with tempfile.TemporaryDirectory(prefix="actor-probe-") as directory:
        scratch = Path(directory)
        before = scratch / "before"
        before.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
            tree.extractall(before, filter="data")
        test = scratch / "test_actor.py"
        test.write_bytes((root / "tests/test_harness_actor_env.py").read_bytes())
        home = scratch / "home"
        home.mkdir()
        for label, source, expected in [("before", before, 1), ("after", root, 0)]:
            print(f"{label}: real harness launch -> private child tool", flush=True)
            for name in ["harness.py", "opencode.py"]:
                digest = hashlib.sha256((source / "shantytown" / name).read_bytes()).hexdigest()
                print(f"  {name} sha256: {digest}", flush=True)
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--tb=line",
                 "-p", "no:cacheprovider", "-c", "/dev/null",
                 "--basetemp", str(scratch / (label + "-data")), str(test)],
                cwd=scratch, env={"HOME": str(home), "PATH": os.defpath,
                                  "PYTHONPATH": str(source),
                                  "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
                capture_output=True, text=True)
            # Normalize private fixture paths, preserving test output and status.
            print(result.stdout.replace(str(scratch), "<scratch>"), end="", flush=True)
            print(result.stderr.replace(str(scratch), "<scratch>"), end="", flush=True)
            if result.returncode != expected:
                raise SystemExit(f"{label}: unexpected probe exit {result.returncode}")
        print("Confirmed: inherited actor fails before; all three card actors pass after.")
        print("Private harness/tool doubles only; no tracker write or live launch.")


if __name__ == "__main__":
    main()
