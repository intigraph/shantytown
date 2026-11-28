"""`st inbox -d` to an OFF-HOST recipient (aegis-az0a40).

THE DEFECT: the durable path computed `live = not offhost and ...`, so a peer
host's administrator was never nudged and the report said "recipient not
live" — measured false against an administrator that was up and busy, while
`st go` reached the same pane through the declared peer.

The contract these pin:
  · local live      -> send-keys, pointer closed, exit 0 (unchanged)
  · local not live  -> "recipient not live", exit 0 (unchanged)
  · off-host, peer declared, relay delivers -> nudged over the SAME ssh
    transport as the ephemeral relay, pointer closed, exit 0
  · off-host, cannot nudge -> "off-host: not nudged (<why>)", NEVER "not live",
    pointer left open, exit 0 — the durable persist already succeeded
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from shantytown import cli
from shantytown.cli import main, OK

PEER_SSH = "user@peer.example"
PEER_ROOT = "/opt/st/.shanty"


def crew(tmp_path: Path, **agents) -> Path:
    d = tmp_path / "crew"
    d.mkdir(exist_ok=True)
    for n, spec in agents.items():
        (d / f"{n}.json").write_text(json.dumps(spec))
    return tmp_path


def declare_host(root: Path, name: str, peer: bool = True) -> None:
    body = f'[host]\nname = "{name}"\n'
    if peer:
        body += f'\n[host.peers.host-b]\nssh = "{PEER_SSH}"\nroot = "{PEER_ROOT}"\n'
    (root / "shantytown.toml").write_text(body)


def fake_panes(monkeypatch, *live):
    sent = []

    class FakeTmux:
        def __init__(self, socket=None, *, root=None):
            self.socket = socket
            self.delivery_root = root

        def exists(self, pane):
            return pane in live

        def send(self, pane, msg):
            sent.append((pane, msg))

        def capture(self, pane, *a, **k):
            return ""

    monkeypatch.setattr(cli, "Tmux", FakeTmux)
    monkeypatch.setattr(cli, "_looks_stranded", lambda panes, pane: False)
    return sent


def ssh_result(monkeypatch, rc=0, out="", err="", raises=None):
    calls = []

    class Res:
        returncode = rc
        stdout = out
        stderr = err

    real = subprocess.run

    def fake_run(argv, **kw):
        if not argv or argv[0] != "ssh":
            return real(argv, **kw)         # e.g. st's own version stamp
        calls.append(argv)
        if raises:
            raise raises
        return Res()

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def two_admins(tmp_path, monkeypatch, *, peer=True):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setenv("SHANTY_AGENT", "ada")
    root = crew(tmp_path,
                ada={"role": "administrator", "pane": "shanty-ada", "host": "host-a"},
                bea={"role": "administrator", "pane": "shanty-bea", "host": "host-b"},
                wu={"role": "lead", "reports_to": "ada", "pane": "shanty-wu",
                    "host": "host-a"})
    declare_host(root, "host-a", peer=peer)
    return root


def durable(root, agent, msg, *extra):
    return main(["--root", str(root), "--backend", "files", "inbox", "-d",
                 *extra, agent, msg])


def open_messages(root):
    box = root / "inbox"
    return [json.loads(p.read_text()) for p in sorted(box.glob("msg-*.json"))
            if not json.loads(p.read_text()).get("read")]


# ------------------------------------------------------------------ local --

def test_local_live_recipient_is_sent_and_pointer_closed(tmp_path, monkeypatch, capsys):
    root = two_admins(tmp_path, monkeypatch)
    sent = fake_panes(monkeypatch, "shanty-wu")
    calls = ssh_result(monkeypatch)
    assert durable(root, "wu", "hello") == OK
    out = capsys.readouterr().out
    assert "live to shanty-wu" in out and "pointer closed" in out
    assert sent and sent[0][0] == "shanty-wu"
    assert calls == []                      # nothing crossed a host boundary
    assert open_messages(root) == []


def test_local_not_live_recipient_still_says_not_live(tmp_path, monkeypatch, capsys):
    root = two_admins(tmp_path, monkeypatch)
    fake_panes(monkeypatch)                 # no pane is up
    ssh_result(monkeypatch)
    assert durable(root, "wu", "hello") == OK
    out = capsys.readouterr().out
    assert "recipient not live" in out
    assert len(open_messages(root)) == 1


# --------------------------------------------------------------- off-host --

def test_offhost_recipient_is_nudged_through_the_peer(tmp_path, monkeypatch, capsys):
    root = two_admins(tmp_path, monkeypatch)
    sent = fake_panes(monkeypatch, "shanty-bea")   # a same-NAMED local pane: irrelevant
    calls = ssh_result(monkeypatch, rc=0, out="  -> bea    sent to pane shanty-bea\n")
    assert durable(root, "bea", "ping from a") == OK
    out = capsys.readouterr().out
    assert "not live" not in out
    assert "+ live on host host-b via " + PEER_SSH in out
    assert "pointer closed on live delivery" in out
    assert sent == []                       # never typed into the local namesake
    argv = calls[0]
    assert argv[0] == "ssh" and PEER_SSH in argv
    remote = argv[-1]
    assert "SHANTY_AGENT=ada" in remote
    assert f"--root {PEER_ROOT} inbox bea 'ping from a'" in remote
    assert open_messages(root) == []        # durable persisted, then closed


def test_offhost_without_a_declared_peer_says_not_nudged(tmp_path, monkeypatch, capsys):
    root = two_admins(tmp_path, monkeypatch, peer=False)
    fake_panes(monkeypatch)
    calls = ssh_result(monkeypatch)
    assert durable(root, "bea", "ping") == OK
    out = capsys.readouterr().out
    assert "off-host: not nudged (no [host.peers.host-b] declared" in out
    assert "not live" not in out
    assert calls == []
    assert len(open_messages(root)) == 1    # the durable half is intact


def test_old_local_stop_cannot_override_newer_peer_heartbeat(tmp_path, monkeypatch, capsys):
    from shantytown.owned_work import OwnedWork
    root = two_admins(tmp_path, monkeypatch)
    local = OwnedWork(root)
    local.stop('bea', at=100, reason='old local process observation')
    peer = OwnedWork(tmp_path / 'peer')
    peer.heartbeat('bea', now=200)
    assert peer.snapshot()['bea']['state'] == 'live'
    before = local.snapshot()
    ticks = []
    monkeypatch.setattr(cli, '_owned_work_tick', lambda *a, **kw: ticks.append(kw))
    fake_panes(monkeypatch)
    ssh_result(monkeypatch, out='  -> bea    sent to pane shanty-bea\n')
    assert durable(root, 'bea', 'peer is live') == OK
    captured = capsys.readouterr()
    assert '+ live on host host-b' in captured.out
    assert 'stopped-owner' not in captured.err
    assert 'must decide ownership' not in captured.err
    assert ticks == []
    assert local.snapshot() == before


def test_unreachable_peer_with_old_local_stop_is_unknown(tmp_path, monkeypatch, capsys):
    from shantytown.owned_work import OwnedWork
    root = two_admins(tmp_path, monkeypatch)
    OwnedWork(root).stop('bea', at=100)
    fake_panes(monkeypatch)
    ssh_result(monkeypatch, rc=255, err='peer unreachable')
    assert durable(root, 'bea', 'pending delivery') == OK
    captured = capsys.readouterr()
    assert 'recipient state UNKNOWN' in captured.out
    assert 'stopped-owner' not in captured.err
    assert 'must decide ownership' not in captured.err
    assert len(open_messages(root)) == 1


def test_local_stopped_owner_still_warns_and_wakes(tmp_path, monkeypatch, capsys):
    from shantytown.owned_work import OwnedWork
    root = two_admins(tmp_path, monkeypatch)
    OwnedWork(root).stop('wu', at=100)
    ticks = []
    monkeypatch.setattr(cli, '_owned_work_tick', lambda *a, **kw: ticks.append(kw))
    fake_panes(monkeypatch)
    ssh_result(monkeypatch)
    assert durable(root, 'wu', 'local stopped work') == OK
    captured = capsys.readouterr()
    assert 'stopped-owner: wu stopped' in captured.err
    assert 'must decide ownership' in captured.err
    assert ticks == [{'card': None, 'wake_owner': 'wu'}]


def test_offhost_ssh_failure_says_not_nudged_and_keeps_exit_zero(
        tmp_path, monkeypatch, capsys):
    root = two_admins(tmp_path, monkeypatch)
    fake_panes(monkeypatch)
    ssh_result(monkeypatch, rc=255, err="ssh: connect to host peer.example: No route\n")
    assert durable(root, "bea", "ping") == OK
    out = capsys.readouterr().out
    assert "off-host: not nudged (ssh to host host-b" in out
    assert "No route" in out
    assert "not live" not in out
    assert len(open_messages(root)) == 1


def test_offhost_timeout_says_not_nudged(tmp_path, monkeypatch, capsys):
    root = two_admins(tmp_path, monkeypatch)
    fake_panes(monkeypatch)
    ssh_result(monkeypatch, raises=subprocess.TimeoutExpired("ssh", 45))
    assert durable(root, "bea", "ping") == OK
    out = capsys.readouterr().out
    assert "off-host: not nudged (host host-b" in out and "TimeoutExpired" in out
    assert len(open_messages(root)) == 1


def test_offhost_remote_refusal_is_reported_and_pointer_stays_open(
        tmp_path, monkeypatch, capsys):
    root = two_admins(tmp_path, monkeypatch)
    fake_panes(monkeypatch)
    ssh_result(monkeypatch, rc=2, err="  could not tell: pane shanty-bea is not there\n")
    assert durable(root, "bea", "ping") == OK
    out = capsys.readouterr().out
    assert "off-host: not nudged (host host-b did not deliver live (exit 2)" in out
    assert "is not there" in out
    assert len(open_messages(root)) == 1


def test_offhost_dry_run_names_the_relay_and_writes_nothing(tmp_path, monkeypatch, capsys):
    root = two_admins(tmp_path, monkeypatch)
    fake_panes(monkeypatch)
    calls = ssh_result(monkeypatch)
    assert durable(root, "bea", "ping", "-n") == OK
    out = capsys.readouterr().out
    assert f"+ live relay via ssh {PEER_SSH} -> host host-b" in out
    assert calls == [] and open_messages(root) == []


@pytest.mark.parametrize('owner_state', ['live', 'down', 'unknown', 'error'])
def test_local_process_observation_uses_current_owner_state(
        tmp_path, monkeypatch, capsys, owner_state):
    from shantytown.owned_work import OwnedWork
    root = two_admins(tmp_path, monkeypatch)
    service = OwnedWork(root)
    service.confirmed_down('wu', now=100,
                           reason='confirmed cycle refusal; stranded work')
    before = service.snapshot()
    fake_panes(monkeypatch, 'shanty-wu')

    def observe(self, pane):
        if owner_state == 'error':
            raise OSError('process census unavailable')
        return owner_state
    monkeypatch.setattr(cli.Tmux, 'owner_state', observe, raising=False)
    ticks = []
    monkeypatch.setattr(cli, '_owned_work_tick', lambda *a, **kw: ticks.append(kw))
    assert durable(root, 'wu', 'local observation control') == OK
    captured = capsys.readouterr()
    assert 'live to shanty-wu' in captured.out
    assert service.snapshot() == before
    if owner_state == 'live':
        assert 'stopped-owner' not in captured.err
        assert 'must decide ownership' not in captured.err
        assert ticks == []
    else:
        assert 'stopped-owner: wu stopped' in captured.err
        assert ticks == [{'card': None, 'wake_owner': 'wu'}]


def test_live_pane_does_not_undo_explicit_local_stop(tmp_path, monkeypatch, capsys):
    from shantytown.owned_work import OwnedWork
    root = two_admins(tmp_path, monkeypatch)
    OwnedWork(root).stop('wu', at=100)
    fake_panes(monkeypatch, 'shanty-wu')
    monkeypatch.setattr(cli.Tmux, 'owner_state', lambda self, pane: 'live', raising=False)
    ticks = []
    monkeypatch.setattr(cli, '_owned_work_tick', lambda *a, **kw: ticks.append(kw))
    assert durable(root, 'wu', 'deliberate stop control') == OK
    captured = capsys.readouterr()
    assert 'stopped-owner: wu stopped' in captured.err
    assert ticks == [{'card': None, 'wake_owner': 'wu'}]
