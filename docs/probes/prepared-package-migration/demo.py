"""Private synthetic packages only; process custody and filesystem mocked."""
import argparse
from contextlib import redirect_stderr
import hashlib
import io
from pathlib import Path
import subprocess
import tempfile
from types import ModuleType
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--base", default="bb9f8d2a4503c0b4b9c1721185f52316e5ccfc6a")
args = parser.parse_args()
root = Path(__file__).resolve().parents[3]
code = subprocess.check_output(["git", "show", args.base + ":shantytown/codex_packages.py"], cwd=root)
after = (root / "shantytown/codex_packages.py").read_bytes()
print("Synthetic stopped package + already-prepared empty disk target")
print("Custody/filesystem MOCKED; no live daemon or production migration")
for label, source in (("before", code), ("after", after)):
    module = ModuleType("package_demo")
    exec(compile(source, "package_demo.py", "exec"), module.__dict__)
    with tempfile.TemporaryDirectory() as temp, patch.object(module, "filesystem", return_value="ext4"), patch.object(module, "quarantine_custody", return_value={"coverage": "FIXTURE-MOCKED"}):
        temp = Path(temp)
        home = temp / "old"
        old = home / "packages/app-server-daemon"
        binary = old / "releases/version/bin/codex"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"synthetic package")
        binary.chmod(0o755)
        (old / "current").symlink_to("releases/version")
        durable = temp / "shared/daemon"
        module.prepare(temp / "fresh", durable)
        lock = durable / "install.lock"
        lock.touch()
        inode = lock.stat().st_ino
        try:
            with redirect_stderr(io.StringIO()):
                module.migrate_stopped(home, durable)
        except RuntimeError as error:
            assert label == "before" and "shared package differs" in str(error)
            assert not old.is_symlink()
            print("before: REFUSED; original preserved; empty target cannot accept package")
        else:
            assert label == "after" and old.is_symlink() and old.resolve() == durable
            assert lock.stat().st_ino == inode
            retained = [p for p in old.parent.glob(".stopped-daemon-*") if p.is_dir()]
            assert len(retained) == 1 and (retained[0] / "current/bin/codex").read_bytes() == b"synthetic package"
            print("after: PASS; shared payload verified; native lock inode preserved")
            print("original retained/HOLD; no capacity-recovery or deployment claim")
print("after implementation SHA256 " + hashlib.sha256(after).hexdigest())
