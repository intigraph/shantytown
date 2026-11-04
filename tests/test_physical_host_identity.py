"""Private display hostnames must not fork crew identity or lifecycle fences."""
import hashlib
import json
import os
import subprocess
import socket
from types import SimpleNamespace

import pytest

from shantytown import cli, deployment, governor_metrics, harness
from shantytown import host_identity, owned_work_graph as graph
from shantytown import query_identity, quipu_provenance
from shantytown.owned_work import OwnedWork
from shantytown.protocols import Agent
from shantytown.tmux import NullPanes
from test_owned_work_graph import Registry


@pytest.fixture
def namespace(monkeypatch):
    monkeypatch.setattr(socket, 'gethostname', lambda: 'ada')
    monkeypatch.setenv(host_identity.ENV, 'Host-A.example')
    monkeypatch.delenv('QUIPU_HOST', raising=False)
    return 'Host-A.example'


def test_unpinned_hostname_and_existing_producer_hash_remain_exact(tmp_path, monkeypatch):
    monkeypatch.delenv(host_identity.ENV, raising=False)
    monkeypatch.setattr(socket, 'gethostname', lambda: 'Original-Mac.local')
    expected = hashlib.sha256(('Original-Mac.local\0' + str(tmp_path.resolve())).encode()).hexdigest()
    assert host_identity.physical_hostname() == 'Original-Mac.local'
    assert graph.producer(tmp_path) == 'urn:shantytown:owned-work:' + expected


def test_pin_preserves_original_producer_across_display_hostname_changes(tmp_path, namespace, monkeypatch):
    expected = hashlib.sha256((namespace + '\0' + str(tmp_path.resolve())).encode()).hexdigest()
    before = graph.producer(tmp_path)
    monkeypatch.setattr(socket, 'gethostname', lambda: 'bea')
    assert before == graph.producer(tmp_path) == 'urn:shantytown:owned-work:' + expected
    # A separate actual source still gets a separate producer.
    monkeypatch.setenv(host_identity.ENV, 'Host-B.example')
    assert graph.producer(tmp_path) != before


def test_retained_head_and_receipt_survive_namespace_and_rollback(tmp_path, monkeypatch):
    monkeypatch.delenv(host_identity.ENV, raising=False)
    monkeypatch.setattr(socket, 'gethostname', lambda: 'Host-A.example')
    monkeypatch.setattr(graph, '_set_comment', lambda r, iri, payload: r.set_comment(iri, payload))
    service, registry = OwnedWork(tmp_path), Registry()
    service.launch('ada', now=100)
    graph.flush(tmp_path, registry)
    source = graph.producer(service.root)
    first = graph._head(registry, source)[1]
    assert first['host'] == 'Host-A.example'
    monkeypatch.setenv(host_identity.ENV, 'Host-A.example')
    monkeypatch.setattr(socket, 'gethostname', lambda: 'ada')
    service.stop('ada', at=200)
    graph.flush(tmp_path, registry)
    head = graph._head(registry, source)[1]
    assert head['revision'] > first['revision'] and head['host'] == first['host']
    assert head['agents'][0]['state'] == 'stopped'
    monkeypatch.delenv(host_identity.ENV)
    monkeypatch.setattr(socket, 'gethostname', lambda: 'Host-A.example')
    assert graph.producer(service.root) == source
    assert graph._head(registry, source)[1] == head
    # Pinning does not relax cross-host refusal or replay fences.
    head['host'] = 'foreign-host'
    iri = graph._head(registry, source)[0]
    registry.rows[iri] = [dict(payload=json.dumps(head))]
    with pytest.raises(ValueError, match='another source host'):
        graph._head(registry, source)


@pytest.mark.parametrize('value', ['', 'bad host', 'bad\nhost', '../host', '\u2603', 'a' * 254])
def test_malformed_pin_refuses_without_falling_back(namespace, monkeypatch, value):
    monkeypatch.setenv(host_identity.ENV, value)
    with pytest.raises(ValueError, match='invalid pinned'):
        host_identity.physical_hostname()


def test_quipu_read_and_write_attribution_keep_physical_host(namespace, monkeypatch):
    assert query_identity.read_headers()['X-Quipu-Host'] == namespace.lower()
    assert quipu_provenance.headers()['X-Quipu-Host'] == namespace
    monkeypatch.setenv('QUIPU_HOST', 'explicit-host')
    assert query_identity.read_headers()['X-Quipu-Host'] == 'explicit-host'
    assert quipu_provenance.headers()['X-Quipu-Host'] == 'explicit-host'


def test_governor_push_groups_keep_original_instance(namespace, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(governor_metrics, '_push', lambda url, job, instance, body, **kw: calls.append((job, instance)))
    status = governor_metrics.publish(tmp_path, [], url='http://metrics.invalid', env={})
    assert status in (governor_metrics.OK, governor_metrics.NOTHING_TO_SAY)
    assert calls and all(instance == 'Host-A' for _, instance in calls)


def test_invalid_pin_cannot_publish_under_display_hostname(namespace, tmp_path, monkeypatch):
    monkeypatch.setenv(host_identity.ENV, '')
    calls = []
    monkeypatch.setattr(governor_metrics, '_push', lambda *a, **kw: calls.append(a))
    assert governor_metrics.publish(tmp_path, [], url='http://metrics.invalid') == governor_metrics.COULD_NOT_RENDER
    assert calls == []


def test_declared_fleet_host_and_local_inbox_stay_local(namespace, tmp_path, capsys):
    (tmp_path / 'shantytown.toml').write_text('[host]\nname = "host-a"\n')
    assert deployment.local_host(tmp_path) == 'host-a'
    args = SimpleNamespace(root=tmp_path, backend='files', dry_run=True)
    assert cli._inbox_durable(args, Agent(name='bea', host='host-a'), 'fixture', NullPanes()) == 0
    out = capsys.readouterr().out
    assert 'recipient down' in out and 'off-host' not in out and 'relay' not in out


def test_local_codex_launch_carries_pin_and_preserves_inherited_pin(namespace, tmp_path):
    command = harness.get('codex').launch(Agent(name='ada', role='worker'), str(tmp_path / 'config.toml'))
    assert 'SHANTY_PHYSICAL_HOST=Host-A.example ' in command
    assert 'SHANTY_PHYSICAL_HOST=ada ' not in command


def test_remote_daemon_and_attached_tui_carry_same_pin(namespace, tmp_path):
    (tmp_path / 'shantytown.toml').write_text('[env]\nSHANTY_REMOTE_CONTROL = "true"\n')
    config = tmp_path / 'settings/codex/worker/config.toml'
    managed = config.parent / 'packages/standalone/current/codex'
    managed.parent.mkdir(parents=True)
    managed.write_text('')
    command = harness.get('codex').launch(Agent(name='ada', role='worker'), str(config), root=tmp_path)
    assert 'codex remote-control start' in command
    assert command.count('SHANTY_PHYSICAL_HOST=Host-A.example ') >= 2
    assert command.count('QUIPU_HOST=Host-A.example ') >= 2
    assert 'SHANTY_PHYSICAL_HOST=ada ' not in command


def test_governor_census_filters_by_declared_host_in_namespace(namespace, tmp_path, monkeypatch):
    (tmp_path / 'shantytown.toml').write_text('[host]\nname = "host-a"\n')
    cards = [Agent(name='ada', host='host-a'), Agent(name='bea', host='host-b')]
    monkeypatch.setattr(cli, '_panes', lambda a: NullPanes())
    monkeypatch.setattr(cli, '_registry', lambda a: SimpleNamespace(all=lambda: SimpleNamespace(exact=lambda: cards)))
    rows = cli._governor_agents(SimpleNamespace(root=tmp_path))
    assert [(r['name'], r['host']) for r in rows] == [('ada', 'host-a')]


@pytest.mark.parametrize('explicit', [None, 'declared-host'])
def test_actual_tool_child_inherits_standard_quipu_host(namespace, tmp_path, monkeypatch, explicit):
    if explicit is not None:
        monkeypatch.setenv('QUIPU_HOST', explicit)
    binary = tmp_path / 'bin/codex'
    binary.parent.mkdir()
    binary.write_text('#!/usr/bin/python3\nimport json,os\nprint(json.dumps({k:os.environ.get(k) for k in ["SHANTY_PHYSICAL_HOST","QUIPU_HOST"]}))\n')
    binary.chmod(0o755)
    monkeypatch.setenv('PATH', str(binary.parent) + os.pathsep + os.environ['PATH'])
    command = harness.get('codex').launch(Agent(name='ada', role='worker'), str(tmp_path / 'config.toml'))
    result = subprocess.run(['/bin/sh', '-c', command], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {'SHANTY_PHYSICAL_HOST': namespace, 'QUIPU_HOST': explicit or namespace}
