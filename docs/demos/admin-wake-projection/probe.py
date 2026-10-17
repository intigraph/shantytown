"""Compare normal private provisioning with the merged pre-fallback source."""
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
BASE = "ce995db60403bb1ccfd084a15cf2133f69b04ebc"


def measure(module, root, mode):
    from shantytown.protocols import Agent
    ws = root / "admin"
    ws.mkdir(exist_ok=True)
    config = root / "shantytown.toml"
    config.write_text(
        f'[admin_wake_budget]\nmode="{mode}"\nagents=["admin"]\n')
    module.provision(Agent(name="admin", role="administrator", harness="claude",
                           workspace=str(ws)), root)
    raw = (ws / ".claude" / module.CONSENT_TEMPLATE).read_bytes()
    data = json.loads(raw)
    count = sum("shantytown.admin_wake_budget" in h.get("command", "")
                for groups in data["hooks"].values()
                for group in groups for h in group.get("hooks", []))
    return count, raw


def main():
    source = subprocess.check_output(
        ["git", "show", f"{BASE}:shantytown/provision.py"], cwd=ROOT, text=True)
    with tempfile.TemporaryDirectory(prefix="admin-projection-demo-") as td:
        root = Path(td)
        home = root / "home"
        home.mkdir()
        with patch.dict(os.environ, {"HOME": str(home), "PATH": os.defpath}, clear=True):
            from shantytown import provision as candidate
            baseline = types.ModuleType("shantytown._projection_demo_base")
            baseline.__package__ = "shantytown"
            baseline.__file__ = str(ROOT / "shantytown/provision.py")
            exec(compile(source, "retained-provision-base.py", "exec"), baseline.__dict__)
            print(f"Private source fixture; baseline {BASE[:12]}; no live settings")
            for mode in ("off", "advise"):
                fixture = root / mode
                fixture.mkdir()
                old_count, old_bytes = measure(baseline, fixture, mode)
                new_count, new_bytes = measure(candidate, fixture, mode)
                print(f"{mode}: budget hooks {old_count} -> {new_count}; "
                      f"bytes identical={old_bytes == new_bytes}")
                assert old_count == 0
                assert new_count == (1 if mode == "advise" else 0)
                if mode == "off":
                    assert old_bytes == new_bytes
            again, _ = measure(candidate, root / "advise", "advise")
            rollback, _ = measure(candidate, root / "advise", "off")
            print(f"repeat advise: {again}; rollback off: {rollback}")
            assert (again, rollback) == (1, 0)


if __name__ == "__main__":
    main()
