"""Recorded CLI fixture: no real daemon, account, mobile client or pairing code."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch


def invoke(source, arguments):
    env = dict(os.environ, PYTHONPATH=str(source), ST_QUIET_ALIASES="1")
    return subprocess.run(
        [sys.executable, "-c", "from shantytown.cli import main; raise SystemExit(main())", *arguments],
        env=env, cwd=source, capture_output=True, text=True,
    )


if __name__ == "__main__":
    source = Path(__file__).resolve().parents[3]
    before = Path(os.environ["BEFORE_SRC"])
    print("BEFORE: base 2c88041, st agent remote list --json", flush=True)
    result = invoke(before, ["agent", "remote", "list", "--json"])
    print(result.stderr.strip(), flush=True)
    print("exit:", result.returncode, flush=True)
    assert result.returncode == 2 and "invalid choice" in result.stderr

    sys.path.insert(0, str(source))
    from shantytown import cli, agent_remote
    from shantytown.protocols import Agent, Answer

    class Registry:
        def all(self):
            return Answer([Agent("alice", harness="codex"), Agent("bob", harness="codex")], "fixture", True)

        def get(self, name):
            assert name == "alice"
            return Agent(name, harness="codex")

    class Control:
        expired = False

        def __init__(self, name, timeout):
            assert 0 < timeout <= 30
            if name == "bob":
                raise agent_remote.Inactive("no existing daemon; nothing launched")
            assert name == "alice"

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def rpc(self, method, params):
            if method == "remoteControl/status/read":
                return dict(status="connected", serverName="demo-host", environmentId="synthetic-environment")
            assert method == "remoteControl/pairing/start" and params == {"manualCode": True}
            return dict(environmentId="synthetic-environment", manualPairingCode="EXAMPLE-NOT-A-CREDENTIAL",
                        expiresAt=1 if self.expired else 4102444800, pairingCode="synthetic-provider-field")

    with tempfile.TemporaryDirectory(prefix="st-remote-demo-") as directory:
        root = Path(directory)
        (root / "shantytown.toml").write_text('[env]\nSHANTY_BACKEND="files"\n')
        actual = agent_remote.run
        def run(args, registry):
            return actual(args, registry, control_factory=Control)

        with patch.object(cli, "_registry", return_value=Registry()), patch.object(agent_remote, "run", run), patch.object(agent_remote, "local_host", return_value="demo-host"):
            for arguments in (["list", "--json"], ["pair", "alice", "--dry-run", "--json"], ["pair", "alice", "--json"]):
                print("AFTER (synthetic transport): st agent remote", " ".join(arguments), flush=True)
                code = cli.main(["--root", str(root), "agent", "remote", *arguments])
                print("exit:", code, flush=True)
                assert code == 0
            Control.expired = True
            print("NEGATIVE: same pair command, expired synthetic response", flush=True)
            assert cli.main(["--root", str(root), "agent", "remote", "pair", "alice", "--json"]) == 2
            print("expired response withheld; exit 2; no lifecycle commands", flush=True)
