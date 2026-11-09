#!/usr/bin/env python3
"""Run identical offline scheduling controls against pinned base and candidate."""
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[3]
BASE = "01f983b40f72292ded1420efe08b506499e32513"
CONTROLS = [
    "tests/test_tend.py::test_overdue_has_service_before_slow_cycle_and_recovery",
    "tests/test_sweep_rotation.py::test_overdue_service_preserves_the_other_sweeps_cursor",
    "tests/test_sweep_rotation.py::test_overdue_does_not_bypass_the_time_budget",
]


def main():
    archive = subprocess.check_output(["git", "archive", BASE, "shantytown"], cwd=ROOT)
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory)
        # Archive is generated from this repository's pinned source, never an
        # external download. Reject links/paths outside the private fixture.
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            for member in bundle.getmembers():
                if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                    raise ValueError("unsupported source archive member")
                if Path(member.name).is_absolute() or ".." in Path(member.name).parts:
                    raise ValueError("source archive path escaped fixture")
            for member in bundle.getmembers():
                target = fixture / member.name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.extractfile(member) as source:
                        target.write_bytes(source.read())
        (fixture / "tests").mkdir()
        for name in ("conftest.py", "test_tend.py", "test_sweep_rotation.py"):
            (fixture / "tests" / name).write_bytes((ROOT / "tests" / name).read_bytes())
        env = {**os.environ, "PYTHONPATH": str(fixture), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
        print("Actual tend/rotation, synthetic 39.4s recovery + 98.6s cycle; no service, network or notification actions.", flush=True)
        for label, expected in (("base", 1), ("candidate", 0)):
            if label == "candidate":
                for name in ("cli.py", "sweep_rotation.py"):
                    (fixture / "shantytown" / name).write_bytes((ROOT / "shantytown" / name).read_bytes())
            print(f"\n{label}: same three scheduling controls", flush=True)
            completed = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=no", "--disable-warnings", *CONTROLS], cwd=fixture, env=env)
            if completed.returncode != expected:
                raise SystemExit(f"unexpected {label} exit {completed.returncode}; expected {expected}")
        print("PASS: overdue runs after supervision, without resetting the other sweeps' cursor or bypassing the budget.", flush=True)
        print("Source fixture only; scheduled delivery, bytes and latency remain separate acceptance.", flush=True)


if __name__ == "__main__":
    main()
