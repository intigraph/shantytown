"""Compare emitted shim launch setup in private filesystem fixtures."""
import ast
from pathlib import Path
import os
import shlex
import subprocess
import tempfile

BASE = "fd30ffc9024a9730875a88ec0abff09fcaf07f46"

def emitter(source):
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "codex_path_shim_setup")
    namespace = {"Path": Path, "shlex": shlex}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "harness fixture", "exec"), namespace)
    return namespace[node.name]

before = subprocess.check_output(["git", "show", BASE + ":shantytown/harness.py"], text=True)
after = Path("shantytown/harness.py").read_text()
print("Private launch-setup fixtures; no agent or real HOME link is started/touched.")
print("base:", BASE)
for label, source in (("before", before), ("after", after)):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        payload = root / "payload"
        payload.write_text("#!/bin/sh\nexit 0\n")
        payload.chmod(0o700)
        setup = emitter(source)(payload, root / "bin")
        subprocess.run(setup, shell=True, check=True)
        link = root / "bin/codex"
        os.utime(link, ns=(1_000_000_000, 1_000_000_000), follow_symlinks=False)
        first = link.lstat()
        subprocess.run(setup + " && " + shlex.quote(str(link)), shell=True, check=True)
        last = link.lstat()
        stable = (first.st_ino, first.st_mtime_ns, first.st_ctime_ns) == (last.st_ino, last.st_mtime_ns, last.st_ctime_ns)
        print(label, "unchanged-target launch:", "stat preserved" if stable else "stat rewritten")
        print("mtime_ns:", first.st_mtime_ns, "->", last.st_mtime_ns)
        link.unlink()
        link.symlink_to(root / "removed")
        subprocess.run(setup, shell=True, check=True)
        print(label, "changed-target repair:", link.readlink() == payload)
        assert stable == (label == "after")
        assert link.readlink() == payload
