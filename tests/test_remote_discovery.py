"""Local labels and prerequisites must not claim advertised names or phone use."""
import json
import os
import sys
from types import SimpleNamespace

import pytest

from shantytown import agent_remote as remote
from shantytown.protocols import Agent, Answer


class Registry:
    def __init__(self, cards):
        self.cards = cards

    def all(self):
        return Answer(self.cards, "fixture", True)


class Connected:
    def __init__(self, *_):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def rpc(self, method, params):
        assert method == "remoteControl/status/read", "discovery must not pair, enable or launch"
        return {"status": "connected", "serverName": "same-host"}


def test_duplicate_names_are_reported_without_inventing_advertised_identity(monkeypatch, capsys):
    monkeypatch.setattr(remote, "local_host", lambda _: "host-a")
    cards = [Agent(name, harness="codex", host="host-a") for name in ("alice", "bob")]
    args = SimpleNamespace(remote_action="list", json=True, timeout=1)
    assert remote.run(args, Registry(cards), control_factory=Connected) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["local_label"] for row in rows] == ["host-a/alice", "host-a/bob"]
    assert all(row["server_name"] == "same-host" for row in rows)
    assert all(row["duplicate_server_name"] for row in rows)
    assert all(row["phone_visibility"] == "unverified" for row in rows)


def test_unresolved_host_does_not_invent_a_unique_host_label(monkeypatch, capsys):
    monkeypatch.setattr(remote, "local_host", lambda _: None)
    args = SimpleNamespace(remote_action="list", json=True, timeout=1)
    assert remote.run(args, Registry([Agent("alice", harness="codex")]), control_factory=Connected) == 0
    row, = json.loads(capsys.readouterr().out)
    assert row["local_label"] is None
    assert row["duplicate_server_name"] is False  # Only the observed listing, not all phone entries.


def setup_root(tmp_path, enabled="true"):
    root = tmp_path / "root"
    home = root / "settings/codex/worker"
    home.mkdir(parents=True)
    (home / "config.toml").write_text("")
    (root / "shantytown.toml").write_text(f'[env]\nSHANTY_REMOTE_CONTROL = "{enabled}"\n')
    return root, home


@pytest.mark.parametrize("enabled", ["true", "false"])
def test_missing_payload_and_explicit_optout_are_readonly(tmp_path, enabled):
    root, home = setup_root(tmp_path, enabled)
    before = sorted(root.rglob("*"))
    card = Agent("alice", harness="codex")
    result = remote.prerequisites(card, [card], root)
    assert result == {"remote_configured": enabled == "true", "managed_payload": "missing",
                      "phone_visibility": "unverified"}
    assert sorted(root.rglob("*")) == before
    assert not (home / "packages").exists()


def test_agent_override_takes_precedence_and_stale_pointer_is_not_repaired(tmp_path):
    root, role = setup_root(tmp_path)
    binary = role / "packages/standalone/releases/1.0/codex"
    binary.parent.mkdir(parents=True)
    binary.write_text("fixture")
    binary.chmod(0o700)
    current = binary.parents[2] / "current"
    current.symlink_to("missing-release")
    card = Agent("alice", harness="codex")
    assert remote.prerequisites(card, [card], root)["managed_payload"] == "missing"
    assert os.readlink(current) == "missing-release"
    override = root / "settings/codex/agent-alice"
    override.mkdir(parents=True)
    (override / "config.toml").write_text("")
    selected = override / "packages/standalone/current/codex"
    selected.parent.mkdir(parents=True)
    selected.write_text("fixture")
    selected.chmod(0o700)
    assert remote.prerequisites(card, [card], root)["managed_payload"] == "present"
    assert os.readlink(current) == "missing-release"


def test_non_linux_identity_is_unsupported_not_inactive(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "darwin")
    identity = tmp_path / "shantytown/codex/alice/app-server-daemon/daemon.pid"
    identity.parent.mkdir(parents=True)
    identity.write_text(json.dumps({"pid": os.getpid()}))
    with pytest.raises(remote.RemoteError, match="unsupported") as error:
        with remote.Control("alice", 1):
            pytest.fail("connected without native process/peer proof")
    assert not isinstance(error.value, remote.Inactive)
