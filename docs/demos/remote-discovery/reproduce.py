"""Compare status-only discovery against the retained base; no real daemon."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import agent_remote as candidate
from shantytown.protocols import Agent, Answer

BASE = "0ed92183c61e3dfad8f94e8b3da5abbc8dd82c4a"


class Registry:
    def all(self):
        return Answer([Agent(n, harness="codex", host="fixture-host")
                       for n in ("alice", "bob")], "fixture", True)


class StatusOnly:
    def __init__(self, *_):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def rpc(self, method, params):
        assert method == "remoteControl/status/read", "writes are forbidden"
        return {"status": "connected", "serverName": "same-host"}


def show(module, label):
    module.local_host = lambda _: "fixture-host"
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = module.run(SimpleNamespace(remote_action="list", json=True, timeout=1),
                            Registry(), control_factory=StatusOnly)
    assert result == 0
    rows = json.loads(output.getvalue())
    assert [r["server_name"] for r in rows] == ["same-host", "same-host"]
    keys = ("agent", "server_name", "local_label", "duplicate_server_name", "phone_visibility")
    print(label)
    print(json.dumps([{k: row.get(k) for k in keys} for row in rows], indent=2))
    return rows


def main():
    source = subprocess.check_output(
        ["git", "show", f"{BASE}:shantytown/agent_remote.py"], cwd=ROOT, text=True)
    base = ModuleType("shantytown._remote_discovery_base")
    base.__package__ = "shantytown"
    exec(compile(source, "<retained base agent_remote.py>", "exec"), base.__dict__)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    print("Synthetic status-only provider; no real daemon, pairing or phone calls.")
    print(f"Base {BASE}; candidate source {head}")
    show(base, "BEFORE: repeated provider name without local disambiguation")
    rows = show(candidate, "AFTER: local labels and explicit collision/visibility limits")
    assert [r["local_label"] for r in rows] == ["fixture-host/alice", "fixture-host/bob"]
    assert all(r["duplicate_server_name"] and r["phone_visibility"] == "unverified" for r in rows)
    print("Provider names stay unchanged; phone visibility remains unverified.")


if __name__ == "__main__":
    main()
