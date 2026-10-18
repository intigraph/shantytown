#!/usr/bin/env python3
"""Execute the emitted Codex hook on isolated, synthetic workspace memory."""
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[3]
BASE = "c666ed268a277d57b0db63cf12b789d42cbe984d"
sys.path.insert(0, str(ROOT))
from shantytown import codex


with tempfile.TemporaryDirectory(prefix="crew-memory-demo-") as directory:
    fixture = Path(directory)
    before = fixture / "before"
    before.mkdir()
    archive = subprocess.check_output(["git", "archive", BASE, "shantytown"], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(before, filter="data")
    home = fixture / "home"
    home.mkdir()
    root = fixture / "store"
    (root / "crew").mkdir(parents=True)
    workspace = fixture / "workspace"
    workspace.mkdir()
    (root / "crew/fixture.json").write_text(json.dumps({
        "role": "worker", "workspace": str(workspace), "harness": "codex",
    }))
    key = re.sub(r"[^a-zA-Z0-9]", "-", str(workspace.resolve()))
    index = home / ".claude/projects" / key / "memory/MEMORY.md"
    index.parent.mkdir(parents=True)
    index.write_text("SYNTHETIC MEMORY SENTINEL\nLATEST SYNTHETIC DIRECTIVE\n")
    settings = codex.settings_for_role("worker", root=root)
    commands = [h["command"] for g in settings["hooks"]["SessionStart"]
                for h in g["hooks"] if "shantytown.session_anchor" in h["command"]]
    assert len(commands) == 1
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    print(f"Synthetic source-checkout fixture: base={BASE}; candidate={head}")
    for label, source, expected in [("BEFORE", before, False), ("AFTER", ROOT, True)]:
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("SHANTY_", "ST_"))}
        env.update(HOME=str(home), SHANTY_ROOT=str(root), SHANTY_AGENT="fixture",
                   SHANTY_BACKEND="files", PYTHONPATH=str(source))
        result = subprocess.run(shlex.split(commands[0]), input="{}", text=True,
                                capture_output=True, env=env, cwd=fixture, timeout=15)
        assert result.returncode == 0, result.stderr
        context = json.loads(result.stdout)["hookSpecificOutput"]
        text = context["additionalContext"]
        present = "SYNTHETIC MEMORY SENTINEL" in text
        assert present == expected
        assert "[st anchor" in text
        print(json.dumps({"arm": label, "event": context["hookEventName"],
                          "hook_exit": result.returncode, "anchor_present": True,
                          "memory_present": present,
                          "latest_directive_present": "LATEST SYNTHETIC DIRECTIVE" in text,
                          "pane_started_or_cycled": False}, sort_keys=True))
    assert index.read_text() == "SYNTHETIC MEMORY SENTINEL\nLATEST SYNTHETIC DIRECTIVE\n"
    print("PASS: same input, memory absent -> present; original index unchanged; no pane launch.")
