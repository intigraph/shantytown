"""Synthetic native directories and transport only; no crew session or network."""
import copy
import json
from pathlib import Path

import pytest

from shantytown import memory_lifecycle as life
from shantytown.memory_remote import Unproven
from test_memory_sync import Projected


def fixture(tmp_path):
    native, outbox, staging = (tmp_path / name for name in ('native', 'outbox', 'staging'))
    for root in (native, outbox, staging):
        root.mkdir(mode=0o700)
    (native / 'MEMORY.md').write_bytes(b'# Index\r\n[Topic](topic.md)\r\n')
    (native / 'topic.md').write_bytes('λ\n'.encode())
    plan = life.Plan(True, 'https://example.test', 'urn:example:deployment',
                     'urn:example:project', 'legacy', str(native), str(outbox), str(staging))
    remote = Projected()
    settings = {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'existing-stop'}]}]},
                'env': {'SYNTHETIC': 'preserved'}, 'permissions': {'allow': ['Read']}}
    return plan, remote, settings


def prepare_complete(plan, remote, settings):
    pending = life.prepare(plan, remote, settings)
    assert pending['ingest_status'] == 'pending'
    assert pending['native_files'] == 'UNCHANGED_EXISTING_SOURCE'
    assert pending['generation'] == plan.source
    return life.prepare(plan, remote, settings)


def journal(plan):
    return json.loads((Path(plan.outbox) / 'memory-native.json').read_bytes())


def test_prepare_start_native_edit_stop_roundtrip_and_no_change(tmp_path):
    plan, remote, settings = fixture(tmp_path)
    original = copy.deepcopy(settings)
    old = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in Path(plan.source).iterdir()}
    result = prepare_complete(plan, remote, settings)
    generated = Path(result['generation'])
    assert {p.name: p.read_bytes() for p in generated.iterdir()} == {k: v[0] for k, v in old.items()}
    assert journal(plan)['generation'] is None  # Prepared is NOT actually started.
    emitted = json.loads(Path(result['settings']).read_bytes())
    assert emitted['autoMemoryDirectory'] == str(generated)
    assert emitted['env']['SHANTY_MEMORY_GENERATION'] == generated.name
    assert emitted['hooks'] == settings['hooks'] and emitted['permissions'] == settings['permissions']
    assert emitted['env']['SYNTHETIC'] == 'preserved' and settings == original
    # This is a synthetic harness consumer reading its actual emitted setting,
    # not evidence that an installed Claude session has used it.
    assert (Path(emitted['autoMemoryDirectory']) / 'MEMORY.md').read_bytes() == old['MEMORY.md'][0]
    life.acknowledge(plan, remote, generated.name, 'start')
    assert journal(plan)['generation'] == generated.name and journal(plan)['pending'] is None
    (generated / 'topic.md').write_text('new native edit λ\r\n', newline='')
    life.acknowledge(plan, remote, generated.name, 'stop')
    assert life.synchronize(plan, remote)['status'] == 'accepted'
    assert remote.writes[-1]['text'] == 'new native edit λ\r\n'
    next_result = life.prepare(plan, remote, settings)
    assert next_result['generation'] != result['generation']
    assert (Path(next_result['generation']) / 'topic.md').read_bytes() == 'new native edit λ\r\n'.encode()
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in Path(plan.source).iterdir()} == old
    life.acknowledge(plan, remote, Path(next_result['generation']).name, 'start')
    count = len(remote.writes)
    paths = set(Path(plan.staging).iterdir())
    again = life.prepare(plan, remote, settings)
    assert again == next_result
    assert len(remote.writes) == count and set(Path(plan.staging).iterdir()) == paths


def test_interrupted_prepare_keeps_old_root_active_and_reconciles_later_edits(tmp_path):
    plan, remote, settings = fixture(tmp_path)
    first = prepare_complete(plan, remote, settings)
    assert journal(plan)['generation'] is None
    source = Path(plan.source) / 'topic.md'
    source.write_text('late edit after prepared but before any launch')
    assert life.synchronize(plan, remote)['status'] == 'accepted'
    assert remote.writes[-1]['text'] == source.read_text()
    second = life.prepare(plan, remote, settings)
    assert second['generation'] != first['generation']
    assert (Path(first['generation']) / 'topic.md').read_bytes() == 'λ\n'.encode()
    with pytest.raises(Unproven, match='differs'):
        life.acknowledge(plan, remote, Path(first['generation']).name, 'start')


def test_wrong_owner_or_changed_plan_cannot_adopt_another_selection(tmp_path):
    from dataclasses import replace
    plan, remote, settings = fixture(tmp_path)
    prepare_complete(plan, remote, settings)
    with pytest.raises(Unproven, match='identity'):
        life.synchronize(replace(plan, source=str(tmp_path / 'different')), remote)
    with pytest.raises(Unproven, match='missing'):
        life.acknowledge(plan, remote, None, 'start')
    with pytest.raises(Unproven, match='differs'):
        life.acknowledge(plan, remote, 'memory-generation-' + 'f' * 32, 'stop')


def test_pending_generation_tamper_is_retained_and_refused(tmp_path):
    plan, remote, settings = fixture(tmp_path)
    result = prepare_complete(plan, remote, settings)
    (Path(result['generation']) / 'topic.md').write_text('unexpected offline change')
    with pytest.raises(Unproven, match='pending native generation changed'):
        life.prepare(plan, remote, settings)
    assert (Path(result['generation']) / 'topic.md').read_text() == 'unexpected offline change'


def test_observed_external_edit_during_staging_refuses_selection(tmp_path, monkeypatch):
    plan, remote, settings = fixture(tmp_path)
    while life.synchronize(plan, remote)['status'] == 'pending':
        pass
    original = life.stage
    def edit_then_stage(files, parent):
        (Path(plan.source) / 'topic.md').write_text('external editor')
        return original(files, parent)
    monkeypatch.setattr(life, 'stage', edit_then_stage)
    with pytest.raises(Unproven, match='changed during handoff'):
        life.prepare(plan, remote, settings)
    assert not (Path(plan.outbox) / 'memory-native.json').exists()
    assert (Path(plan.source) / 'topic.md').read_text() == 'external editor'
    assert len(list(Path(plan.staging).iterdir())) == 1  # Unselected, retained.


@pytest.mark.parametrize('change', [dict(enabled='true'), dict(typo=True),
    dict(account=42), dict(source='relative'), dict(server='https://u:secret@example.test')])
def test_config_refuses_instead_of_silent_activation(tmp_path, change):
    from dataclasses import asdict
    plan, _, _ = fixture(tmp_path)
    data = asdict(plan)
    data.update(change)
    with pytest.raises(ValueError):
        life.parse({'alpha': data})


def test_default_off_settings_have_no_memory_hook_or_selection(tmp_path):
    from shantytown.config import load
    from shantytown.protocols import Agent
    from shantytown.runtime import claude_settings_for_role
    assert load(tmp_path).memory == {}
    assert life.hooks(tmp_path, 'start') == []
    assert life.prepare_launch(tmp_path, Agent('alpha', 'worker'), 'existing.json') == 'existing.json'
    assert 'memory_lifecycle' not in json.dumps(claude_settings_for_role('worker', tmp_path))


def test_unknown_hook_fails_open_but_reports_unknown_without_body(tmp_path, monkeypatch, capsys):
    from shantytown import memory_deadline
    monkeypatch.setenv('SHANTY_AGENT', 'alpha')
    monkeypatch.setattr(memory_deadline, '_run', lambda *a, **k: (_ for _ in ()).throw(Unproven('private body')))
    assert life.main(['--root', str(tmp_path), '--event', 'stop']) == 0
    captured = capsys.readouterr()
    assert 'UNKNOWN' in captured.err and 'private body' not in captured.err
    assert captured.out == ''


def test_liveness_distinguishes_trigger_source_ingest_and_native_projection(tmp_path):
    plan, remote, settings = fixture(tmp_path)
    first = prepare_complete(plan, remote, settings)
    path = Path(plan.outbox) / 'memory-liveness.json'
    live = json.loads(path.read_bytes())
    assert live['status'] == 'accepted'
    assert live['ingest_accepted_head'] == remote.head
    assert 'producer_last_change' in live and 'projection_last_start' not in live
    source_changed = live['producer_last_change']
    ingested = live['ingest_last_advance']
    life.acknowledge(plan, remote, Path(first['generation']).name, 'start')
    assert life.synchronize(plan, remote)['status'] == 'unchanged'
    stable = json.loads(path.read_bytes())
    assert stable['producer_last_change'] == source_changed
    assert stable['ingest_last_advance'] == ingested
    assert stable['projection_generation'] == Path(first['generation']).name
    assert stable['producer_last_scan'] >= source_changed
    remote.projection_error = True
    with pytest.raises(Unproven):
        life.synchronize(plan, remote)
    unknown = json.loads(path.read_bytes())
    assert unknown['status'] == 'unknown'
    assert unknown['ingest_last_advance'] == ingested


def test_enabled_plan_does_not_invent_codex_native_writeback(tmp_path, monkeypatch):
    from dataclasses import replace
    from shantytown import config
    from shantytown.protocols import Agent
    plan, _, _ = fixture(tmp_path)
    monkeypatch.setattr(config, 'load', lambda root: replace(config.Config(), memory={'alpha': plan}))
    card = Agent('alpha', 'worker', harness='codex')
    assert life.prepare_launch(tmp_path, card, 'original-codex.toml') == 'original-codex.toml'


def test_actual_config_hook_emission_and_private_source_setting_reader(tmp_path):
    from dataclasses import asdict
    from shantytown.config import load
    from shantytown.runtime import claude_settings_for_role
    plan, _, _ = fixture(tmp_path)
    values = asdict(plan)
    text = '[memory.alpha]\n' + '\n'.join(key + ' = ' + ('true' if value is True else json.dumps(value))
        for key, value in values.items())
    (tmp_path / 'shantytown.toml').write_text(text)
    assert load(tmp_path).memory['alpha'] == plan
    emitted = claude_settings_for_role('worker', tmp_path)
    for event, spelling in [('SessionStart', 'start'), ('Stop', 'stop')]:
        commands = [hook['command'] for group in emitted['hooks'][event] for hook in group['hooks']]
        assert sum('shantytown.memory_lifecycle' in command for command in commands) == 1
        assert any('--event ' + spelling in command for command in commands)
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps(emitted))
    path.chmod(0o600)
    assert life._settings(path) == emitted
    path.chmod(0o666)
    with pytest.raises(Unproven, match='unsafe'):
        life._settings(path)


def test_runtime_compose_and_launch_stamp_use_same_prepared_artifact(tmp_path, monkeypatch):
    from shantytown.protocols import Agent
    from shantytown.runtime import ClaudeRuntime
    chosen = tmp_path / 'private-prepared.json'
    chosen.write_text('{}')
    seen = []
    monkeypatch.setattr(life, 'prepare_launch', lambda root, card, path:
        seen.append(path) or str(chosen))
    runtime = ClaudeRuntime(None, lambda card: str(tmp_path / 'original.json'), root=tmp_path)
    card = Agent('alpha', 'worker', harness='claude')
    command = runtime.compose(card)
    assert '--settings ' + str(chosen) in command
    assert runtime.settings_path(card) == str(chosen)
    assert seen == [str(tmp_path / 'original.json')]


def test_runtime_does_not_cache_unmodified_role_artifact(tmp_path):
    from shantytown.protocols import Agent
    from shantytown.runtime import ClaudeRuntime
    runtime = ClaudeRuntime(None, lambda card: str(tmp_path / (card.role + '.json')), root=tmp_path)
    worker = Agent('alpha', 'worker', harness='claude')
    runtime.compose(worker)
    lead = Agent('alpha', 'lead', harness='claude')
    assert runtime.settings_path(lead) == str(tmp_path / 'lead.json')


def test_readonly_settings_resolution_uses_acknowledged_artifact_and_detects_stale_base(tmp_path, monkeypatch):
    from shantytown import config
    from dataclasses import replace
    from shantytown.protocols import Agent
    plan, remote, settings = fixture(tmp_path)
    result = prepare_complete(plan, remote, settings)
    life.acknowledge(plan, remote, Path(result['generation']).name, 'start')
    base = tmp_path / 'base-settings.json'
    base.write_text(json.dumps(settings))
    base.chmod(0o600)
    monkeypatch.setattr(config, 'load', lambda root: replace(config.Config(), memory={'alpha': plan}))
    monkeypatch.setattr(life, '_selected', lambda root, name: (plan, remote))
    card = Agent('alpha', 'worker', harness='claude')
    count = len(remote.writes)
    assert life.selected_settings(tmp_path, card, str(base)) == result['settings']
    assert len(remote.writes) == count
    base.write_text('{}')
    with pytest.raises(Unproven, match='base changed'):
        life.selected_settings(tmp_path, card, str(base))


@pytest.mark.parametrize('override', [dict(autoMemoryEnabled=False),
    dict(autoMemoryDirectory='/not-the-declared-memory'),
    dict(env={'CLAUDE_CODE_DISABLE_AUTO_MEMORY': '1'})])
def test_deliberate_native_hold_or_foreign_root_refuses_before_ingest(tmp_path, override):
    plan, remote, settings = fixture(tmp_path)
    settings.update(override)
    with pytest.raises(Unproven):
        life.prepare(plan, remote, settings)
    assert remote.writes == [] and remote.projection_reads == 0
    assert not list(Path(plan.staging).iterdir())


def test_partial_upload_launch_keeps_original_source_and_natural_hooks_progress(tmp_path):
    plan, remote, settings = fixture(tmp_path)
    result = life.prepare(plan, remote, settings)
    assert result['ingest_status'] == 'pending'
    emitted = json.loads(Path(result['settings']).read_bytes())
    assert emitted['autoMemoryDirectory'] == plan.source
    assert emitted['env']['SHANTY_MEMORY_GENERATION'] == 'original'
    assert not list(Path(plan.staging).iterdir())
    life.acknowledge(plan, remote, 'original', 'start')
    assert journal(plan)['generation'] is None
    assert life.synchronize(plan, remote)['status'] == 'accepted'
    assert len(remote.writes) == 2
    life.acknowledge(plan, remote, 'original', 'stop')
    assert life.synchronize(plan, remote)['status'] == 'unchanged'
    assert len(remote.writes) == 2
    live = json.loads((Path(plan.outbox) / 'memory-liveness.json').read_bytes())
    assert 'projection_last_start' not in live


def test_verified_same_crew_account_switch_keeps_owner_head_and_native_files(tmp_path):
    from dataclasses import replace
    plan, remote, settings = fixture(tmp_path)
    first = prepare_complete(plan, remote, settings)
    generation = Path(first['generation'])
    life.acknowledge(plan, remote, generation.name, 'start')
    before = remote.head, len(remote.writes), {p.name: p.read_bytes() for p in generation.iterdir()}
    # Subscription attribution changes; authenticated logical crew owner does
    # not. No new person, empty baseline adoption or foreign file scan occurs.
    switched = replace(plan, account='second-selected-account')
    second = life.prepare(switched, remote, settings)
    assert second['generation'] == first['generation']
    assert (remote.head, len(remote.writes), {p.name: p.read_bytes() for p in generation.iterdir()}) == before
    (generation / 'topic.md').write_text('same crew, selected second account')
    assert life.synchronize(switched, remote)['status'] == 'accepted'
    assert remote.writes[-1]['account'] == 'second-selected-account'
    assert remote.writes[-1]['owner'] == remote.owner.wire()


def test_actual_selected_account_is_attribution_and_optional_pin_is_enforced(tmp_path, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    from shantytown import config
    plan, remote, _ = fixture(tmp_path)
    crew = tmp_path / 'crew'
    crew.mkdir()
    (crew / 'alpha.json').write_text(json.dumps(dict(role='worker', harness='claude', account='second')))
    cfg = replace(config.Config(), memory={'alpha': replace(plan, account='')},
                  accounts={'second': SimpleNamespace(name='second', harness='claude')})
    monkeypatch.setattr(config, 'load', lambda _: cfg)
    calls = []
    monkeypatch.setattr(life.Client, 'for_agent', lambda *a: calls.append(a) or remote)
    actual, client = life._selected(tmp_path, 'alpha')
    assert actual.account == 'second' and client is remote and len(calls) == 1
    cfg = replace(cfg, memory={'alpha': plan})
    with pytest.raises(Unproven, match='account unsupported'):
        life._selected(tmp_path, 'alpha')
    assert len(calls) == 1
