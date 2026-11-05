"""Real card/CLI round trips; generated commands only, no agent processes."""
import json
from dataclasses import replace

import pytest

from shantytown import cli, harness
from shantytown.files import FilesRegistry
from shantytown.protocols import Agent


def setup_card(tmp_path, monkeypatch, **fields):
    root = tmp_path / 'st'
    reg = FilesRegistry(root / 'crew')
    reg.set(Agent(name='scratch', role='administrator', **fields))
    monkeypatch.setattr(cli, '_harness_lane_held', lambda *a: False)
    return root, reg


def switch(root, target, *extra):
    return cli.main(['--root', str(root), '--backend', 'files', 'agent',
                     'harness', 'scratch', target, *extra])


def test_chrome_and_both_models_survive_round_trip(tmp_path, monkeypatch):
    root, reg = setup_card(tmp_path, monkeypatch, harness='claude',
                           chrome=True, model='claude-fixture')
    assert switch(root, 'codex', '--model', 'codex-fixture') == cli.OK
    codex = reg.get('scratch')
    assert codex.chrome is False
    assert codex.harness_options['claude'] == {'chrome': True, 'model': 'claude-fixture'}
    assert switch(root, 'claude') == cli.OK
    claude = reg.get('scratch')
    assert claude.chrome is True and claude.model == 'claude-fixture'
    assert switch(root, 'codex') == cli.OK
    assert reg.get('scratch').model == 'codex-fixture'


def test_codex_legacy_chrome_warns_without_launch_refusal(tmp_path, capsys):
    card = Agent(name='scratch', harness='codex', chrome=True)
    command = harness.get('codex').launch(card, str(tmp_path / 'codex/config.toml'))
    assert '--chrome' not in command and '--no-chrome' not in command
    assert 'chrome' in capsys.readouterr().err


def test_report_lists_retained_options(tmp_path, monkeypatch, capsys):
    root, reg = setup_card(tmp_path, monkeypatch, harness='claude', chrome=True,
                           model='claude-fixture')
    capsys.readouterr()
    assert cli.main(['--root', str(root), '--backend', 'files', 'agent',
                     'harness', 'scratch']) == cli.OK
    output = capsys.readouterr().out
    assert 'chrome' in output and 'claude-fixture' in output


def test_explicit_default_model_clears_active_alias(tmp_path, monkeypatch):
    root, reg = setup_card(tmp_path, monkeypatch, harness='claude', model='claude-fixture',
                          harness_options={'codex': {'model': None}})
    assert switch(root, 'codex') == cli.OK
    card = reg.get('scratch')
    assert card.model is None and card.harness_options['codex']['model'] is None
    assert harness.resolve_model(card) is None
    assert switch(root, 'claude') == cli.OK
    assert reg.get('scratch').model == 'claude-fixture'


def test_profile_launch_and_projection_preserve_other_harnesses(tmp_path):
    profiles = {'claude': {'model': 'claude-fixture', 'chrome': True},
                'codex': {'model': 'codex-fixture', 'chrome': True, 'future_flag': True}}
    reg = FilesRegistry(tmp_path / 'crew')
    reg.set(Agent(name='scratch', harness='codex', harness_options=profiles))
    reg.set(Agent(name='scratch', role='lead'))
    card = reg.get('scratch')
    assert card.harness_options == profiles and card.harness == 'codex'
    assert harness.resolve_model(card) == 'codex-fixture'
    assert harness.resolve_model(replace(card, harness='claude')) == 'claude-fixture'
    assert '--chrome' in harness.get('claude').launch(
        replace(card, harness='claude'), str(tmp_path / 'worker.json'))


@pytest.mark.parametrize('program', ['codex', 'opencode'])
def test_foreign_options_are_retained_but_never_shell_flags(tmp_path, capsys, program):
    card = Agent(name='scratch', harness=program, harness_options={
        program: {'chrome': True, 'future_flag': 'do-not-execute'}})
    command = harness.get(program).launch(card, str(tmp_path / 'config.toml'))
    assert 'do-not-execute' not in command and '--chrome' not in command
    notice = capsys.readouterr().err
    assert 'chrome' in notice and 'future_flag' in notice and 'retained' in notice


@pytest.mark.parametrize('bad', [[], {'claude': []}, {'claude': {'chrome': 'yes'}},
                               {'claude': {'model': ' '}}, {'claude': {'x': {}}}])
def test_malformed_profile_refuses_before_card_write(tmp_path, bad):
    reg = FilesRegistry(tmp_path / 'crew')
    reg.set(Agent(name='scratch', model='old'))
    path = reg.root / 'scratch.json'
    before = path.read_bytes()
    with pytest.raises(ValueError, match='harness_options'):
        reg.set(Agent(name='scratch', harness_options=bad))
    assert path.read_bytes() == before


def test_config_profiles_and_active_model_override(tmp_path):
    from shantytown.config import load
    (tmp_path / 'shantytown.toml').write_text('''[crew.scratch]
harness = "codex"
[crew.scratch.harness_options.claude]
chrome = true
model = "claude-fixture"
[crew.scratch.harness_options.codex]
model = "codex-fixture"
''')
    card = load(tmp_path).crew['scratch']
    assert harness.resolve_model(card) == 'codex-fixture'
    assert harness.resolve_model(replace(card, model='new-codex')) == 'new-codex'
    assert harness.resolve_model(replace(card, account='selected', model='account-model')) == 'account-model'


def test_harness_dry_run_does_not_migrate_or_backup(tmp_path, monkeypatch):
    root, reg = setup_card(tmp_path, monkeypatch, harness='claude', model='claude-fixture', chrome=True)
    path = reg.root / 'scratch.json'
    before = path.read_bytes()
    assert switch(root, 'codex', '--model', 'codex-fixture', '--dry-run') == cli.OK
    assert path.read_bytes() == before and list(reg.root.glob('*.bak*')) == []


def test_role_pin_and_hold_refuse_before_saved_profile_write(tmp_path, monkeypatch):
    root, reg = setup_card(tmp_path, monkeypatch, harness='claude', model='claude-fixture',
                          harness_options={'codex': {'model': 'codex-fixture'}})
    # A real target role pin still gates an otherwise remembered selection.
    (root / 'shantytown.toml').write_text('[harness.required_by_role]\nadministrator = "claude"\n')
    path = reg.root / 'scratch.json'; before = path.read_bytes()
    assert switch(root, 'codex') == cli.REFUSED
    assert path.read_bytes() == before and list(reg.root.glob('*.bak*')) == []


def test_unknown_profile_options_report_as_retained_not_supported(tmp_path, monkeypatch, capsys):
    root, reg = setup_card(tmp_path, monkeypatch, harness='codex',
                          harness_options={'codex': {'chrome': True}})
    assert cli.main(['--root', str(root), '--backend', 'files', 'agent',
                     'harness', 'scratch']) == cli.OK
    assert 'unsupported, retained: chrome' in capsys.readouterr().out


def test_profile_model_requires_first_target_selection(tmp_path, monkeypatch):
    root, reg = setup_card(tmp_path, monkeypatch, harness='claude',
                          harness_options={'claude': {'model': 'claude-fixture'}})
    path = reg.root / 'scratch.json'; before = path.read_bytes()
    assert switch(root, 'codex') == cli.REFUSED
    assert path.read_bytes() == before and list(reg.root.glob('*.bak*')) == []


def test_explicit_blank_never_overrides_remembered_target(tmp_path, monkeypatch):
    root, reg = setup_card(tmp_path, monkeypatch, harness='claude', model='claude-fixture',
                          harness_options={'codex': {'model': 'codex-fixture'}})
    path = reg.root / 'scratch.json'; before = path.read_bytes()
    assert switch(root, 'codex', '--model', ' ') == cli.REFUSED
    assert path.read_bytes() == before and list(reg.root.glob('*.bak*')) == []
