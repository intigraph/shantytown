"""Runtime replacement must wait, preserve checkpoints and prove new versions."""
from types import SimpleNamespace

import pytest

from shantytown import cycle, runtime_roll as roll, runtime_update as update
from shantytown.protocols import Agent


def world(tmp_path):
    cards = [Agent(name=n, harness="claude") for n in ("a", "b")]
    versions = {c.name: update.Evidence(c.name + "-old", "2.1.319", "2.1.321") for c in cards}
    blocks = {"a": "the input box is not empty", "b": "background tasks running"}
    snapshots = []
    requests = cycle.Requests(tmp_path)
    def checkpoint(card, evidence):
        snapshots.append(card.name)
        return dict(text=f"checkpoint {card.name}: notes and exact next step", item="plate", nodes=["existing"])
    def sweep():
        return roll.sweep(tmp_path, cards, requests=requests,
            observe=lambda root, name: versions[name], boundary=lambda c: blocks[c.name],
            preflight=lambda c: None, checkpoint=checkpoint)
    return cards, versions, blocks, requests, snapshots, sweep


def test_input_and_background_tasks_defer_then_one_replacement_is_requested(tmp_path):
    cards, versions, blocks, requests, snapshots, sweep = world(tmp_path)
    assert sweep() == [] and not snapshots
    assert roll.ledger(tmp_path)["a"]["reason"] == "the input box is not empty"
    blocks.update(a="", b="")
    assert sweep() == ["a"]
    request = requests.pending()["a"]
    assert request["auto"] and request["no_in_place"]
    assert request["quipu_nodes"] == ["existing"]
    assert request["checkpoint"] == request["runtime_update"]["checkpoint"]
    assert sweep() == [] and snapshots == ["a"]
    requests.clear("a")  # launch succeeded; this alone is not a version receipt
    assert sweep() == []
    assert roll.ledger(tmp_path)["a"]["phase"] == "awaiting-version"
    versions["a"] = update.Evidence("a-new", "2.1.321", "2.1.321")
    assert sweep() == ["b"]
    assert roll.ledger(tmp_path)["a"]["phase"] == "completed"
    assert roll.ledger(tmp_path)["a"]["previous"] == "2.1.319"
    receipt = roll.ledger(tmp_path)["a"]["receipt"]
    sweep()
    assert roll.ledger(tmp_path)["a"]["receipt"] == receipt


def test_failed_checkpoint_is_not_retried_or_converted_into_a_request(tmp_path):
    card = Agent(name="a")
    calls = []
    def fail(*args):
        calls.append(True)
        raise RuntimeError("HTTP400 post-state validation refused")
    def sweep():
        return roll.sweep(tmp_path, [card], requests=cycle.Requests(tmp_path),
            observe=lambda *a: update.Evidence("exact", "2.1.319", "2.1.321"),
            boundary=lambda c: "", preflight=lambda c: None, checkpoint=fail)
    assert sweep() == [] and sweep() == []
    assert len(calls) == 1 and not cycle.Requests(tmp_path).pending()
    assert roll.ledger(tmp_path)["a"]["phase"] == "checkpoint-failed"


def test_manual_request_and_unknown_ledger_are_preserved(tmp_path):
    _, _, blocks, requests, snapshots, sweep = world(tmp_path)
    blocks.update(a="", b="")
    requests.request("a", "richer manual checkpoint")
    assert sweep() == [] and snapshots == []
    assert requests.pending()["a"]["checkpoint"] == "richer manual checkpoint"
    requests.path.write_text("broken")
    assert sweep() == [] and requests.path.read_text() == "broken"


def test_machine_checkpoint_requires_exact_readback_and_current_session(tmp_path, monkeypatch):
    evidence = update.Evidence("exact", "2.1.319", "2.1.321")
    monkeypatch.setattr(update, "for_agent", lambda *args: evidence)
    request = dict(checkpoint="saved snapshot", checkpoint_bead="plate",
                   runtime_update=dict(key=evidence.key, session="exact", running=evidence.running,
                                       installed=evidence.installed, checkpoint="saved snapshot"))
    assert not roll.checkpoint_gate(tmp_path, "a", request, []).ok
    comments = [dict(author="actual-st-writer", text="saved snapshot")]
    assert roll.checkpoint_gate(tmp_path, "a", request, comments).ok
    request["checkpoint"] = "changed"
    assert not roll.checkpoint_gate(tmp_path, "a", request, comments).ok
    request["checkpoint"] = "saved snapshot"
    monkeypatch.setattr(update, "for_agent", lambda *args: update.Evidence("other", "2.1.319", "2.1.321"))
    assert not roll.checkpoint_gate(tmp_path, "a", request, comments).ok


def test_newer_install_during_input_deferral_can_replace_same_old_session(tmp_path, monkeypatch):
    evidence = update.Evidence("exact", "2.1.319", "2.1.322")
    monkeypatch.setattr(update, "for_agent", lambda *args: evidence)
    request = dict(checkpoint="snapshot", checkpoint_bead="",
                   runtime_update=dict(key="exact:2.1.319->2.1.321", session="exact",
                                       running="2.1.319", installed="2.1.321", checkpoint="snapshot"))
    assert roll.checkpoint_gate(tmp_path, "a", request, []).ok
    monkeypatch.setattr(update, "for_agent", lambda *args: update.Evidence("exact", "2.1.319", "2.1.320"))
    assert not roll.checkpoint_gate(tmp_path, "a", request, []).ok


def test_no_in_place_rejects_missing_token_before_request_or_pane_changes(tmp_path, monkeypatch, capsys):
    from shantytown import cli, provision
    from test_cycle_self_no_in_place import _self_args
    card = Agent(name="worker", workspace=str(tmp_path))
    monkeypatch.setattr(cli, "_registry", lambda a: SimpleNamespace(get=lambda n: card))
    monkeypatch.setattr(cli, "_cycle_stop_refusal", lambda *a: "")
    def refuse(*args):
        raise provision.ProvisionError("cannot render: no value for HOMELAB_MCP_TOKEN")
    monkeypatch.setattr(provision, "preflight_credentials", refuse)
    assert cli._cmd_cycle(_self_args(tmp_path, no_in_place=True)) == cli.REFUSED
    assert "HOMELAB_MCP_TOKEN" in capsys.readouterr().err
    assert not cycle.Requests(tmp_path).pending()


def test_credential_preflight_resolves_existing_sources_without_projection(tmp_path, monkeypatch):
    from shantytown import config, provision, tooling
    card = Agent(name="worker", workspace=str(tmp_path))
    monkeypatch.setattr(config, "load", lambda *a, **kw: SimpleNamespace(source_document=None))
    manifest = SimpleNamespace(mcp={"server": {"headers": {"Authorization": "Bearer ${HOMELAB_MCP_TOKEN}"}}})
    monkeypatch.setattr(tooling, "load", lambda *a, **kw: manifest)
    monkeypatch.delenv("HOMELAB_MCP_TOKEN", raising=False)
    with pytest.raises(provision.ProvisionError, match="HOMELAB_MCP_TOKEN"):
        provision.preflight_credentials(card, tmp_path)
    directory = tmp_path / "provision"
    directory.mkdir()
    (directory / "secrets.env").write_text("HOMELAB_MCP_TOKEN=synthetic-fixture\n")
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    provision.preflight_credentials(card, tmp_path)
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before
    assert not (tmp_path / ".mcp.json").exists()
    with pytest.raises(provision.ProvisionError, match="store root"):
        provision.preflight_credentials(card, None)


def test_runtime_request_is_not_withdrawn_by_shallow_context(tmp_path):
    from test_auto_cycle import _world, _sweep
    from test_cycle import IDLE
    ac, _, requests, _, _, _ = _world(tmp_path, IDLE)
    ac._save({"kelly": {"prompted_at": 1}})
    requests.request("kelly", "runtime checkpoint", auto=True, no_in_place=True,
                     runtime_update={"session": "exact"})
    _sweep(ac)
    assert "kelly" in requests.pending()


def test_codex_version_is_bound_to_owned_thread_and_selected_install(tmp_path, monkeypatch):
    import json
    from shantytown import codex_shells, harness, provision
    card = Agent(name="worker", harness="codex")
    transcript = tmp_path / "thread.jsonl"
    header = dict(type="session_meta", payload=dict(id="exact", timestamp="1970-01-01T00:16:41Z",
                                                   cli_version="0.100.0"))
    transcript.write_text(json.dumps(header) + "\n")
    context = dict(payload=dict(session_id="exact", transcript_path=str(transcript)))
    monkeypatch.setattr(codex_shells, "_binding", lambda *args: dict(thread="exact"))
    monkeypatch.setattr(codex_shells, "_json", lambda *args: (context, "digest"))
    monkeypatch.setattr(harness.CodexHarness, "_remote_control", lambda root: True)
    selected = tmp_path / "config.toml"
    selected.write_text("")
    binary = tmp_path / "packages/standalone/current/codex"
    binary.parent.mkdir(parents=True)
    binary.write_text("synthetic binary identity")
    monkeypatch.setattr(provision, "_codex_config", lambda *args: selected)
    probes = []
    def probe(root, **kwargs):
        probes.append(kwargs)
        return "0.101.0"
    monkeypatch.setattr(update, "installed_version", probe)
    result = update._codex_evidence(tmp_path, card, 1000)
    assert result.outdated and result.harness == "codex" and result.session == "exact"
    assert probes == [dict(binary=str(binary), program="codex")]
    context["payload"]["session_id"] = "other"
    assert not update._codex_evidence(tmp_path, card, 1000).outdated
    context["payload"]["session_id"] = "exact"
    header["payload"]["timestamp"] = "1970-01-01T00:16:39Z"
    transcript.write_text(json.dumps(header) + "\n")
    assert not update._codex_evidence(tmp_path, card, 1000).outdated
    assert len(probes) == 1


def test_atomic_auto_admission_never_replaces_a_manual_checkpoint(tmp_path):
    requests = cycle.Requests(tmp_path)
    requests.request("a", "manual checkpoint")
    assert requests.request("a", "automatic", only_if_absent=True) is False
    assert requests.pending()["a"]["checkpoint"] == "manual checkpoint"


def test_process_replacement_resume_brief_does_not_claim_unchanged_runtime():
    from shantytown import resume_brief
    text = resume_brief.compose("worker", checkpoint="stored notes", process_replaced=True)
    assert "process was replaced" in text and "stored notes" in text
    assert "runtime, your tools and your permissions are unchanged" not in text


def test_executor_preserves_current_process_when_credentials_disappear(tmp_path, monkeypatch):
    from shantytown import cli, provision
    card = Agent(name="worker", workspace=str(tmp_path))
    args = SimpleNamespace(root=tmp_path)
    def missing(*args):
        raise provision.ProvisionError("cannot render: no value for HOMELAB_MCP_TOKEN")
    monkeypatch.setattr(provision, "preflight_credentials", missing)
    monkeypatch.setattr(cli, "_cmd_stop", lambda *a: pytest.fail("must not stop live process"))
    monkeypatch.setattr(cli, "_launch", lambda *a, **k: pytest.fail("must not touch pane"))
    result = cli._restart_cycle(args, card, "worker", "pane", None, None,
                                SimpleNamespace(mode=cycle.RELAUNCH), None)
    assert result == (cli.REFUSED, cycle.RELAUNCH)


def test_real_tend_path_requests_and_serves_without_agent_command(tmp_path, monkeypatch):
    from shantytown import cli, provision
    from test_cycle_self_no_in_place import _tend_world
    from tests.test_tend import _Args
    _tend_world(tmp_path, monkeypatch)
    monkeypatch.setattr(update, "for_agent", lambda *a: update.Evidence("exact", "2.1.319", "2.1.321"))
    monkeypatch.setattr(cli, "_automatic_cycle_refusal", lambda *a, **k: "")
    monkeypatch.setattr(provision, "preflight_credentials", lambda *a: None)
    monkeypatch.setattr(cli, "_runtime_checkpoint", lambda *a: dict(text="stored anchor and notes", item="plate", nodes=["existing"]))
    seen = []
    monkeypatch.setattr(cli, "_cmd_cycle", lambda args: seen.append(args) or cli.OK)
    cli._tend_once(_Args(tmp_path, backend="files"))
    served = [a for a in seen if a.agent == "worker"]
    assert len(served) == 1
    assert served[0].no_in_place and served[0]._runtime_update
    assert served[0].reason == "stored anchor and notes"
    assert served[0].quipu_node == ["existing"]


@pytest.mark.parametrize('peer_state', ['current', 'unknown', 'awaiting-version', 'owner-unreachable'])
def test_actual_tend_wrapper_collects_peers_under_admission(tmp_path, monkeypatch, peer_state):
    from contextlib import contextmanager
    from shantytown import cli, config, fleet, fleet_governor, provision

    peers = {'peer': 'fixture-peer'}
    monkeypatch.setattr(config, 'load', lambda root: SimpleNamespace(
        host_peers=peers, host_name='local', host_admission_owner='owner'))
    admission_calls, collected, snapshots = [], [], []

    @contextmanager
    def admission(root, host, actual_peers, **kwargs):
        admission_calls.append((root, host, actual_peers, kwargs))
        yield SimpleNamespace(unreachable=peer_state == 'owner-unreachable')

    monkeypatch.setattr(fleet_governor, 'admission_lock', admission)

    def collect(actual_peers):
        collected.append(actual_peers)
        return [dict(host='peer', error='unreachable' if peer_state == 'unknown' else None,
                     agents=[dict(name='remote', live=True,
                                  runtime_update=dict(phase=peer_state))])]

    monkeypatch.setattr(fleet, 'collect', collect)
    monkeypatch.setattr(update, 'for_agent', lambda *a: update.Evidence('exact', '2.1.319', '2.1.321'))
    monkeypatch.setattr(cli, '_cycle_stop_refusal', lambda *a: '')
    monkeypatch.setattr(cli, '_automatic_cycle_refusal', lambda *a: '')
    monkeypatch.setattr(provision, 'preflight_credentials', lambda *a: None)

    def checkpoint(*args):
        snapshots.append(True)
        return dict(text='stored checkpoint', item='plate', nodes=['existing'])

    monkeypatch.setattr(cli, '_runtime_checkpoint', checkpoint)
    result = cli._runtime_roll_sweep(
        SimpleNamespace(root=tmp_path), [Agent(name='worker', harness='claude')],
        SimpleNamespace(exists=lambda pane: True), object(), lambda text: None)
    assert admission_calls == [(tmp_path, 'local', peers, dict(owner='owner', local_required=True))]
    assert collected == ([] if peer_state == 'owner-unreachable' else [peers])
    pending = cycle.Requests(tmp_path).pending()
    if peer_state == 'current':
        assert result == ['worker'] and snapshots == [True]
        assert pending['worker']['no_in_place'] and pending['worker']['runtime_update']
    else:
        assert result == [] and snapshots == [] and pending == {}


def test_corrupt_version_ledger_does_not_admit_another_replacement(tmp_path):
    _, _, blocks, requests, snapshots, sweep = world(tmp_path)
    requests.path.parent.mkdir(parents=True)
    (requests.path.parent / "runtime-roll.json").write_text("malformed")
    blocks.update(a="", b="")
    assert sweep() == [] and snapshots == [] and not requests.pending()


def test_competing_sweep_cannot_observe_or_write_while_admission_is_owned(tmp_path):
    import fcntl
    _, _, blocks, requests, snapshots, sweep = world(tmp_path)
    requests.path.parent.mkdir(parents=True)
    with (requests.path.parent / "runtime-roll.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        blocks.update(a="", b="")
        assert sweep() == [] and snapshots == [] and not requests.pending()
    assert sweep() == ["a"]


def test_request_generation_recovers_after_version_ledger_write_failed(tmp_path, monkeypatch):
    _, versions, blocks, requests, snapshots, sweep = world(tmp_path)
    blocks.update(a="", b="")
    real_write = roll.write_json_atomic
    calls = 0
    def fail(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("final version ledger unavailable")
        real_write(*args)
    monkeypatch.setattr(roll, "write_json_atomic", fail)
    with pytest.raises(OSError):
        sweep()
    assert "a" in requests.pending()
    monkeypatch.setattr(roll, "write_json_atomic", real_write)
    assert sweep() == [] and snapshots == ["a"]
    requests.clear("a")
    versions["a"] = update.Evidence("a-new", "2.1.321", "2.1.321")
    assert sweep() == ["b"]
    assert roll.ledger(tmp_path)["a"]["receipt"]["before"] == "2.1.319"


def test_peer_unknown_and_inflight_generation_hold_new_local_roll(tmp_path):
    assert roll.peer_block([dict(host="peer", error="unreachable", agents=[])])
    assert roll.peer_block([dict(host="peer", error=None, agents=[dict(name="a", live=True)])])
    peer = dict(host="peer", error=None, agents=[dict(name="a", live=True,
                runtime_update=dict(phase="awaiting-version"))])
    assert "unverified replacement" in roll.peer_block([peer])
    card = Agent(name="local")
    requests = cycle.Requests(tmp_path)
    result = roll.sweep(tmp_path, [card], requests=requests,
        observe=lambda *a: update.Evidence("exact", "2.1.319", "2.1.321"),
        boundary=lambda c: "", preflight=lambda c: None,
        checkpoint=lambda *a: pytest.fail("peer holds admission"), fleet_block=roll.peer_block([peer]))
    assert result == [] and not requests.pending()
    peer["agents"][0]["runtime_update"]["phase"] = "current"
    assert roll.peer_block([peer]) == ""


@pytest.mark.parametrize("failed_write", [1, 2])
def test_failed_ledger_write_never_admits_two_hosts(tmp_path, monkeypatch, failed_write):
    roots = [tmp_path / "host-a", tmp_path / "host-b"]
    cards = [Agent(name="a"), Agent(name="b")]
    requests = [cycle.Requests(root) for root in roots]
    monkeypatch.setattr(update, "_manual_keep", lambda *args: False)
    def sweep(index, evidence, block=""):
        return roll.sweep(roots[index], [cards[index]], requests=requests[index],
            observe=lambda *args: evidence, boundary=lambda card: "",
            preflight=lambda card: None,
            checkpoint=lambda *args: dict(text="durable synthetic checkpoint"),
            fleet_block=block)
    # A peer can legitimately retain this previously published current row.
    sweep(0, update.Evidence("a-old", "2.1.319", "2.1.319"))
    real_write = roll.write_json_atomic
    calls = 0
    def fail(path, value):
        nonlocal calls
        calls += 1
        if calls == failed_write:
            raise OSError("injected ledger failure")
        real_write(path, value)
    with monkeypatch.context() as failure:
        failure.setattr(roll, "write_json_atomic", fail)
        with pytest.raises(OSError, match="injected ledger failure"):
            sweep(0, update.Evidence("a-old", "2.1.319", "2.1.321"))
    published = roll.ledger(roots[0])["a"]
    block = roll.peer_block([dict(host="host-a", error=None,
        agents=[dict(name="a", live=True, runtime_update=published)])])
    admitted = sweep(1, update.Evidence("b-old", "2.1.319", "2.1.321"), block)
    if failed_write == 1:
        assert not requests[0].pending()
        assert admitted == ["b"]  # no first request committed
    else:
        assert "a" in requests[0].pending()
        assert published["phase"] == "requested" and block
        assert admitted == [] and not requests[1].pending()
    assert sum(bool(request.pending()) for request in requests) == 1
