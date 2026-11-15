"""A remote lead is routable without a local lifecycle card; misses stay errors."""
import json

import pytest

from shantytown import quipu, stop_event
from shantytown.answer import CouldNotLook
from shantytown.anchor import anchor
from shantytown.events import FilesEvents
from shantytown.files import FilesRegistry
from shantytown.protocols import Agent
from shantytown.routing_identity import with_remote_lead
from shantytown.tmux import NullPanes


def setup(tmp_path, monkeypatch, *, host="remote"):
    crew = tmp_path / "crew"
    crew.mkdir()
    (crew / "worker.json").write_text(json.dumps({"role": "worker", "reports_to": "coordinator"}))
    (crew / "local-admin.json").write_text(json.dumps({"role": "administrator"}))
    (tmp_path / "shantytown.toml").write_text(
        '[host]\nname="local"\n[env]\nQUIPU_SERVER="http://graph.example"\n'
        'SHANTY_ONTO_NS="http://crew.example/ontology/"\n')
    calls = []
    lead = Agent(name="coordinator", role="administrator", host=host)

    def get(self, name):
        calls.append(name)
        return lead

    monkeypatch.setattr(quipu.QuipuRegistry, "get", get)
    return FilesRegistry(crew), lead, calls


def test_remote_lead_anchor_and_stop_agree_without_local_card(tmp_path, monkeypatch):
    reg, lead, calls = setup(tmp_path, monkeypatch)
    resolved = with_remote_lead(reg, "worker", tmp_path)
    result = anchor("worker", resolved, NullPanes())
    assert result.lead == lead
    assert calls == ["coordinator"]
    assert not (reg.root / "coordinator.json").exists()
    verdict = stop_event._lead_is_up(resolved, NullPanes())("coordinator")
    assert not verdict and "off-host" in verdict.detail
    # The stop sender must use the same resolution before routing and relay.
    monkeypatch.setattr(stop_event, "_my_shells", lambda *a: 0)
    monkeypatch.setattr(stop_event, "_my_context_k", lambda *a: None)
    monkeypatch.setattr(stop_event, "_plate_of", lambda *a: (None, None, []))
    relays = []
    monkeypatch.setattr(stop_event, "_offhost_durable", lambda r, root, to, *a: relays.append((to, r.get(to).host)))
    events = FilesEvents(tmp_path / "events")
    assert stop_event._send(reg, events, NullPanes(), "worker", tmp_path) == 0
    assert relays == [("coordinator", "remote")]
    assert not list(events.pending("local-admin"))


def test_absent_graph_lead_still_refuses(tmp_path, monkeypatch):
    reg, _, _ = setup(tmp_path, monkeypatch)
    def absent(*a):
        raise LookupError("no such graph member")
    monkeypatch.setattr(quipu.QuipuRegistry, "get", absent)
    with pytest.raises(LookupError, match="no such graph member"):
        with_remote_lead(reg, "worker", tmp_path)


@pytest.mark.parametrize("host", [None, "local"])
def test_missing_local_projection_is_not_remote(tmp_path, monkeypatch, host):
    reg, _, _ = setup(tmp_path, monkeypatch, host=host)
    with pytest.raises(LookupError, match="no off-host placement"):
        with_remote_lead(reg, "worker", tmp_path)


def test_local_card_and_offline_deployment_do_not_query(tmp_path, monkeypatch):
    reg, _, calls = setup(tmp_path, monkeypatch)
    card = reg.root / "coordinator.json"
    card.write_text(json.dumps({"role": "administrator"}))
    assert with_remote_lead(reg, "worker", tmp_path) is reg
    card.unlink()
    (tmp_path / "shantytown.toml").unlink()
    with pytest.raises(LookupError):
        with_remote_lead(reg, "worker", tmp_path)
    assert calls == []


def test_failed_graph_read_never_reroutes_to_local_admin(tmp_path, monkeypatch):
    reg, _, _ = setup(tmp_path, monkeypatch)
    def unavailable(*a):
        raise CouldNotLook("graph unavailable")
    monkeypatch.setattr(quipu.QuipuRegistry, "get", unavailable)
    with pytest.raises(CouldNotLook):
        with_remote_lead(reg, "worker", tmp_path)
    events = FilesEvents(tmp_path / "events")
    assert stop_event._send(reg, events, NullPanes(), "worker", tmp_path) == 2
    assert not list(events.pending("local-admin"))
