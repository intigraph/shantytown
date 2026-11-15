"""Inherited legacy hook registrations must not hide stale executable bytes."""
import json

import pytest

from shantytown import provision as P
from shantytown.protocols import Agent


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    monkeypatch.setenv('HOME', str(home))
    ws = home / 'gt' / 'fixture' / 'crew' / 'worker'
    ws.mkdir(parents=True)
    root = tmp_path / 'store'
    root.mkdir()
    source = ws / 'skills' / 'graph-capture' / 'hooks' / 'quipu-session-capture.sh'
    source.parent.mkdir(parents=True)
    (source.parent.parent / 'SKILL.md').write_text('capture installer owns canonical hook\n')
    source.write_text('#!/bin/sh\n# current recipe\n')
    source.chmod(0o755)
    canonical = home / '.gt' / 'hooks' / source.name
    canonical.parent.mkdir(parents=True)
    canonical.write_text('#!/bin/sh\n# stale recipe\n')
    canonical.chmod(0o755)
    registry = ws.parent / '.claude' / 'settings.json'
    registry.parent.mkdir()
    registry.write_text(json.dumps({'hooks': {'Stop': [{'hooks': [
        {'type': 'command', 'command': 'echo unrelated'},
        {'type': 'command', 'command': 'exec "$HOME/.gt/hooks/quipu-session-capture.sh"'},
    ]}]}}))
    return root, ws, source, canonical, registry


def test_registered_stale_hook_refuses_before_projection(legacy):
    root, ws, source, canonical, registry = legacy
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (canonical, registry)}
    with pytest.raises(P.ProvisionError, match='legacy session-capture'):
        P.provision(Agent(name='worker', workspace=str(ws)), root)
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}
    assert not (ws / '.claude').exists()


def test_matching_hook_records_proof_without_changing_registration(legacy):
    from shantytown.legacy_capture import RECEIPT
    import hashlib
    root, ws, source, canonical, registry = legacy
    canonical.write_bytes(source.read_bytes())
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (canonical, registry)}
    P.provision(Agent(name='worker', workspace=str(ws)), root)
    proof = json.loads((ws / RECEIPT).read_text())
    assert proof['status'] == 'verified'
    receipt_mtime = (ws / RECEIPT).stat().st_mtime_ns
    P.provision(Agent(name='worker', workspace=str(ws)), root)
    assert (ws / RECEIPT).stat().st_mtime_ns == receipt_mtime
    assert proof['source_sha256'] == proof['canonical_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}


@pytest.mark.parametrize('damage', ['missing', 'nonexecutable', 'symlink', 'missing-source'])
def test_unverifiable_registered_hook_refuses(legacy, damage):
    root, ws, source, canonical, registry = legacy
    canonical.write_bytes(source.read_bytes())
    if damage == 'missing':
        canonical.unlink()
    elif damage == 'nonexecutable':
        canonical.chmod(0o644)
    elif damage == 'symlink':
        canonical.unlink()
        canonical.symlink_to(source)
    else:
        source.unlink()
    with pytest.raises(P.ProvisionError, match='legacy session-capture'):
        P.provision(Agent(name='worker', workspace=str(ws)), root)


def test_unregistered_stale_hook_is_not_adopted(legacy):
    from shantytown.legacy_capture import RECEIPT
    root, ws, source, canonical, registry = legacy
    registry.write_text('{"hooks": {"Stop": []}}')
    before = canonical.read_bytes(), canonical.stat().st_mtime_ns
    P.provision(Agent(name='worker', workspace=str(ws)), root)
    assert not (ws / RECEIPT).exists()
    assert before == (canonical.read_bytes(), canonical.stat().st_mtime_ns)


def test_manifest_source_wins_over_local_copy(legacy, tmp_path):
    from shantytown import legacy_capture
    root, ws, source, canonical, registry = legacy
    canonical.write_bytes(source.read_bytes())
    declared = tmp_path / 'declared'
    (declared / 'hooks').mkdir(parents=True)
    (declared / 'SKILL.md').write_text('authoritative')
    (declared / 'hooks' / source.name).write_text('newer authoritative recipe')
    class Manifest:
        def sources(self, workspace):
            return [('graph-capture', declared)]
    with pytest.raises(ValueError, match='legacy session-capture'):
        legacy_capture.inspect(ws, Manifest())


def test_managed_override_is_checked_without_generated_settings(legacy):
    root, ws, source, canonical, registry = legacy
    override = ws.parents[3] / '.gt' / 'hooks-overrides' / 'fixture__crew.json'
    override.parent.mkdir(parents=True)
    override.write_text(json.dumps(json.loads(registry.read_text())['hooks']))
    registry.unlink()
    with pytest.raises(P.ProvisionError, match='legacy session-capture'):
        P.provision(Agent(name='worker', workspace=str(ws)), root)


def test_retirement_updates_existing_receipt(legacy):
    from shantytown.legacy_capture import RECEIPT
    root, ws, source, canonical, registry = legacy
    canonical.write_bytes(source.read_bytes())
    card = Agent(name='worker', workspace=str(ws))
    P.provision(card, root)
    registry.write_text('{"hooks": {"Stop": []}}')
    P.provision(card, root)
    assert json.loads((ws / RECEIPT).read_text()) == {'status': 'unregistered'}


def test_receipt_symlink_cannot_redirect_write(legacy, tmp_path):
    from shantytown.legacy_capture import RECEIPT
    root, ws, source, canonical, registry = legacy
    canonical.write_bytes(source.read_bytes())
    target = tmp_path / 'unrelated'
    target.write_text('preserve')
    (ws / RECEIPT).symlink_to(target)
    with pytest.raises(P.ProvisionError, match='legacy session-capture'):
        P.provision(Agent(name='worker', workspace=str(ws)), root)
    assert target.read_text() == 'preserve'
