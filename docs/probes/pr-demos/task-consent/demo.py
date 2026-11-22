import hashlib, json, subprocess, tempfile, types
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd()))
import os
for name in tuple(os.environ):
    if name.startswith(("SHANTY_", "ST_")) or name in ("QUIPU_SERVER", "QUIPU_HOOK_GROUP"):
        os.environ.pop(name)
from shantytown import ephemeral as eph, provision
from shantytown.protocols import Agent

base = subprocess.run(["git", "show", "b4d5a1fa:shantytown/provision.py"], check=True, capture_output=True, text=True).stdout
old = types.ModuleType("shantytown.baseline_provision")
old.__package__ = "shantytown"
exec(compile(base, "baseline_provision.py", "exec"), old.__dict__)
for label, producer in (("BASE b4d5a1fa", old), ("CANDIDATE", provision)):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "root"; root.mkdir()
        ws = Path(d) / "workspace"; ws.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(ws), *args], check=True, capture_output=True, text=True).stdout.strip()
        git("init", "-q"); git("config", "user.name", "Demo"); git("config", "user.email", "demo@example.invalid")
        (ws / "README").write_text("fixture\n"); git("add", "README"); git("commit", "-qm", "fixture")
        rec = dict(name="eph-task-a1b2c3", job="task", harness="claude", workspace=str(ws),
                   item="fixture-item", state=eph.LAUNCHING, kit_settings_sha256=None,
                   worktree_base_sha=git("rev-parse", "HEAD"))
        eph.write(root, rec)
        card = Agent(name=rec["name"], role="worker", harness="claude", workspace=str(ws))
        producer.provision(card, root)
        current = eph.read(root, rec["name"])
        print(label)
        print("  provisioned consent hash recorded:", bool(current["kit_settings_sha256"]))
        print("  trust decision:", eph.trust_surface_refusal(current) or "ALLOW emitted bytes")
        local = ws / ".claude/settings.local.json"
        local.write_bytes(local.read_bytes() + b" ")
        print("  after tampering:", eph.trust_surface_refusal(current))
