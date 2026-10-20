"""Offline operator sequences, not Android or lifecycle acceptance.

Use the real parser/dispatch and an in-memory provider. Every code is synthetic;
no runtime home, daemon, mobile client or credential store is involved.
"""
import json
from types import SimpleNamespace

import pytest

from shantytown import agent_remote as remote, cli
from shantytown.protocols import Agent, Answer


@pytest.fixture
def onboarding(tmp_path, monkeypatch):
    (tmp_path / "shantytown.toml").write_text('[harness]\ndefault = "codex"\n')
    state = SimpleNamespace(connected=True, generation=1, change=False, timeout=False)
    calls = []

    class Registry:
        def get(self, name):
            assert name in {"alice", "carol"}
            return Agent(name)

        def all(self):
            return Answer([self.get("alice"), self.get("carol")], "fixture", True)

    class Provider:
        def __init__(self, name, timeout):
            self.name, self.generation = name, state.generation
            if not state.connected:
                raise remote.Inactive("fixture has no existing daemon; nothing launched")

        def __enter__(self):
            return self

        def __exit__(self, kind, *_):
            if kind is None and state.change:
                state.generation += 1
                raise remote.RemoteError("daemon identity changed; response withheld")

        def rpc(self, method, params):
            calls.append((self.name, self.generation, method))
            environment = f"fixture-environment-{self.generation}"
            if method == "remoteControl/status/read":
                return dict(status="connected", serverName="same-computer-label",
                            environmentId=environment)
            assert method == "remoteControl/pairing/start" and params == {"manualCode": True}
            if state.timeout:
                # Model a response lost after request admission, not proven non-issuance.
                raise TimeoutError("PRIVATE-PROVIDER-DETAIL")
            return dict(environmentId=environment, manualPairingCode="SYNTHETIC-NOT-A-CREDENTIAL",
                        expiresAt=4102444800)

    actual = remote.run
    monkeypatch.setattr(cli, "_registry", lambda _: Registry())
    monkeypatch.setattr(remote, "local_host", lambda _: "fixture-host")
    monkeypatch.setattr(remote, "run", lambda args, registry:
                        actual(args, registry, control_factory=Provider))

    def forbidden(*_, **__):
        pytest.fail("offline sequence attempted a real socket")

    monkeypatch.setattr("socket.socket", forbidden)

    def invoke(*arguments):
        return cli.main(["--root", str(tmp_path), "agent", "remote", *arguments])

    return invoke, state, calls


def starts(calls):
    return [call for call in calls if call[2] == "remoteControl/pairing/start"]


def test_duplicate_computer_label_keeps_explicit_card_routing(onboarding, capsys):
    invoke, _, calls = onboarding
    assert invoke("list", "--json") == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["agent"] for row in rows] == ["alice", "carol"]
    assert {row["server_name"] for row in rows} == {"same-computer-label"}
    assert starts(calls) == []
    calls.clear()
    assert invoke("pair", "carol", "--dry-run", "--json") == 0
    assert json.loads(capsys.readouterr().out)["action"] == "would_pair"
    assert starts(calls) == []
    assert invoke("pair", "carol", "--json") == 0
    row = json.loads(capsys.readouterr().out)
    assert row["agent"] == "carol" and row["harness"] == "codex"
    assert row["manual_pairing_code"] == "SYNTHETIC-NOT-A-CREDENTIAL"
    assert {call[0] for call in calls} == {"carol"}
    assert starts(calls) == [("carol", 1, "remoteControl/pairing/start")]


def test_inactive_then_external_recovery_requires_new_explicit_attempt(onboarding, capsys):
    invoke, state, calls = onboarding
    state.connected = False
    assert invoke("list", "--json") == 0
    assert {row["availability"] for row in json.loads(capsys.readouterr().out)} == {"inactive"}
    assert invoke("pair", "alice", "--json") == 2
    assert capsys.readouterr().out == "" and calls == []
    # Test-input change only: no daemon lifecycle action or mobile persistence model.
    state.connected = True
    assert invoke("pair", "alice", "--dry-run", "--json") == 0
    row = json.loads(capsys.readouterr().out)
    assert row["availability"] == "connected" and "manual_pairing_code" not in row
    assert starts(calls) == []


def test_generation_change_withholds_code_then_rediscovery_uses_new_identity(onboarding, capsys):
    invoke, state, calls = onboarding
    state.change = True
    assert invoke("pair", "alice", "--json") == 2
    output = capsys.readouterr()
    assert output.out == "" and "SYNTHETIC-NOT-A-CREDENTIAL" not in output.err
    assert len(starts(calls)) == 1  # No implicit retry on a new generation.
    state.change = False
    assert invoke("pair", "alice", "--dry-run", "--json") == 0
    assert json.loads(capsys.readouterr().out)["action"] == "would_pair"
    assert len(starts(calls)) == 1
    assert invoke("pair", "alice", "--json") == 0
    assert json.loads(capsys.readouterr().out)["agent"] == "alice"
    assert starts(calls) == [("alice", 1, "remoteControl/pairing/start"),
                             ("alice", 2, "remoteControl/pairing/start")]


def test_pair_timeout_is_unknown_and_followup_inspection_does_not_retry(onboarding, capsys):
    invoke, state, calls = onboarding
    state.timeout = True
    assert invoke("pair", "alice", "--json") == 2
    output = capsys.readouterr()
    assert output.out == "" and "outcome unknown" in output.err
    assert "PRIVATE-PROVIDER-DETAIL" not in output.err and len(starts(calls)) == 1
    assert invoke("pair", "alice", "--dry-run", "--json") == 0
    assert "manual_pairing_code" not in json.loads(capsys.readouterr().out)
    assert len(starts(calls)) == 1
