"""Offline actual renderer/launch contracts; no producer or credential reads."""
import json
import pytest
from shantytown.harness import ClaudeHarness, CodexHarness
from shantytown.protocols import Agent

G = 'DESIRE_PATH_METRICS_PUSHGATEWAY'
P = 'DESIRE_PATH_METRICS_PASSWORD_FILE'
PAIR = {G: 'http://metrics@example.invalid', P: '/fixture/not-read/password'}

@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for key in (G, P):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr('shantytown.harness._crew_launch_identity', lambda *a: ('', ''))


def deployment(root, values):
    (root / 'shantytown.toml').write_text('[env]\n' + '\n'.join(f'{k} = {json.dumps(v)}' for k, v in values.items()))


def test_actual_claude_renderer_carries_pair(tmp_path):
    deployment(tmp_path, {**PAIR, 'QUIPU_SERVER': 'http://graph.example.invalid'})
    h = ClaudeHarness()
    result = json.loads(h.render(h.settings('worker', root=tmp_path), root=tmp_path))
    assert result['env']['QUIPU_SERVER'] == 'http://graph.example.invalid'
    assert {k: result['env'].get(k) for k in PAIR} == PAIR


@pytest.mark.parametrize('harness', [ClaudeHarness, CodexHarness])
def test_actual_launch_carries_pair(tmp_path, harness):
    deployment(tmp_path, PAIR)
    launch = harness().launch(Agent(name='fixture', role='worker'), str(tmp_path / 'settings/config.toml'), root=tmp_path)
    for k, v in PAIR.items():
        assert f'{k}={v} ' in launch


@pytest.mark.parametrize('values', [{G: PAIR[G]}, {P: PAIR[P]}, {**PAIR, G:'http://user:dummy@example.invalid'}, {**PAIR, P:'relative'}, {**PAIR, G:'https://example.invalid/?token=dummy'}])
def test_invalid_pair_refused_before_render_or_launch(tmp_path, values):
    deployment(tmp_path, values)
    with pytest.raises(ValueError, match='DP metrics'):
        ClaudeHarness().settings('worker', root=tmp_path)
    with pytest.raises(ValueError, match='DP metrics'):
        CodexHarness().launch(Agent(name='fixture', role='worker'), str(tmp_path / 'settings/config.toml'), root=tmp_path)


def test_absent_preserves_unowned_claude_values(tmp_path):
    h = ClaudeHarness()
    old = json.dumps({'env': {**PAIR, 'OPERATOR_KEEP': 'untouched'}})
    settings = h.settings('worker', root=tmp_path)
    assert not any(k in settings['env'] for k in PAIR)
    out = json.loads(h.render(settings, old, root=tmp_path))
    assert all(out['env'][k] == v for k, v in PAIR.items())
    assert out['env']['OPERATOR_KEEP'] == 'untouched'


def test_conflict_refuses_without_exposing_values(tmp_path):
    deployment(tmp_path, PAIR)
    old = json.dumps({'env': {G:'http://private-user@private.invalid', P:'/private/location'}})
    with pytest.raises(ValueError, match='DP metrics migration') as err:
        h = ClaudeHarness()
        h.render(h.settings('worker', root=tmp_path), old, root=tmp_path)
    assert 'private' not in str(err.value)


@pytest.mark.parametrize('harness', [ClaudeHarness, CodexHarness])
def test_inherited_conflict_refuses_launch(tmp_path, monkeypatch, harness):
    deployment(tmp_path, PAIR)
    monkeypatch.setenv(G, 'http://old.example.invalid')
    with pytest.raises(ValueError, match='DP metrics migration'):
        harness().launch(Agent(name='fixture', role='worker'), str(tmp_path/'config.toml'), root=tmp_path)


def test_no_ownership_or_deletion_after_two_renders(tmp_path):
    h = ClaudeHarness()
    deployment(tmp_path, PAIR)
    first = h.render(h.settings('worker', root=tmp_path), root=tmp_path)
    deployment(tmp_path, {})
    second = json.loads(h.render(h.settings('worker', root=tmp_path), first, root=tmp_path))
    assert all(second['env'][k] == v for k, v in PAIR.items())


def test_absent_codex_launch_does_not_unset_unowned(tmp_path):
    launch = CodexHarness().launch(Agent(name='fixture', role='worker'), str(tmp_path/'config.toml'), root=tmp_path)
    assert G not in launch and P not in launch


def test_codex_daemon_launch_carries_pair_without_running_it(tmp_path):
    deployment(tmp_path, {**PAIR, 'SHANTY_REMOTE_CONTROL': 'true'})
    cfg = tmp_path / 'settings/codex/worker/config.toml'
    binary = cfg.parent / 'packages/standalone/current/codex'
    binary.parent.mkdir(parents=True)
    binary.write_text('fixture; not executable or invoked')
    launch = CodexHarness().launch(Agent(name='fixture', role='worker'), str(cfg), root=tmp_path)
    assert 'codex remote-control start' in launch
    for key, value in PAIR.items():
        assert launch.count(f'{key}={value} ') >= 2


def test_matching_existing_pair_not_adopted_or_changed(tmp_path):
    deployment(tmp_path, PAIR)
    h = ClaudeHarness()
    old = {'env': {**PAIR, 'OPERATOR_KEEP': 'fixture'}}
    out = json.loads(h.render(h.settings('worker', root=tmp_path), json.dumps(old), root=tmp_path))
    assert all(out['env'][key] == value for key, value in old['env'].items())
    assert not any('ownership' in key for key in out)


def test_absent_preserves_partial_unowned_claude_pair(tmp_path):
    h = ClaudeHarness()
    out = json.loads(h.render(h.settings('worker', root=tmp_path), json.dumps({'env': {G: PAIR[G]}}), root=tmp_path))
    assert out['env'][G] == PAIR[G] and P not in out['env']


def test_malformed_url_refusal_does_not_echo_configuration(tmp_path):
    deployment(tmp_path, {**PAIR, G: 'https://private.example.invalid:badport'})
    with pytest.raises(ValueError, match='DP metrics') as err:
        ClaudeHarness().settings('worker', root=tmp_path)
    assert 'private' not in str(err.value)
