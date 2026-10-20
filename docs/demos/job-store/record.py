"""Run the same private probe through two isolated tmux servers."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

probe = Path(__file__).with_name("probe.py").resolve()
tmux = shutil.which("tmux")
if not tmux:
    raise SystemExit("tmux required")
for label, source in zip(("BASE", "CANDIDATE"), sys.argv[1:]):
    with tempfile.TemporaryDirectory() as d:
        socket = str(Path(d) / "socket")
        output = Path(d) / "result"
        command = [tmux, "-S", socket, "-f", "/dev/null"]
        env = {"HOME": d, "PATH": "/usr/bin:/bin"}
        print(label + ": isolated tmux run-shell; minimal env; private fixture", flush=True)
        try:
            subprocess.run([*command, "new-session", "-d", "-s", "fixture", "sleep 60"],
                           env=env, check=True)
            child = ["env", "-i", f"HOME={d}", "PATH=/usr/bin:/bin",
                     f"PYTHONPATH={Path(source).resolve()}", sys.executable, str(probe)]
            subprocess.run([*command, "run-shell",
                            shlex.join(child) + " > " + shlex.quote(str(output)) + " 2>&1"],
                           env=env, check=True)
            text = output.read_text()
            print(text, end="", flush=True)
            expected = '"terminal_events": 0' if label == "BASE" else '"terminal_events": 1'
            assert expected in text
            assert ('"check_rc": 0' if label == "BASE" else '"check_rc": 2') in text
        finally:
            subprocess.run([*command, "kill-server"], env=env, capture_output=True)
