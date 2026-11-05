import json
from pathlib import Path
from types import SimpleNamespace

from shantytown import cost


def sample():
    return {'groups': [], 'costs': {'price_table_sha256': 'fixture-sha', 'groups': [
        {'rig': 'example', 'bead': 'task-a', 'agent': 'worker', 'harness': 'claude',
         'model': 'example-model', 'basis': 'declared', 'usd': None, 'known_usd': '0.5',
         'tokens': 100, 'priced_tokens': 50, 'unknown_reasons': {'unknown token category': 1}}]}}


def test_partial_dollars_are_not_a_complete_cost_or_receipt():
    result = sample()
    text = cost.metrics(result)
    assert 'st_bead_api_equivalent_usd{' not in text
    assert 'st_bead_api_equivalent_known_usd{' in text
    assert 'price_table_sha256="fixture-sha"} 0.5' in text
    assert cost.receipt(result, 'task-a') is None
    description = cost.price_description(result, 'task-a')
    assert 'UNKNOWN (known subtotal 0.5)' in description
    assert 'priced tokens 50/100' in description
    assert 'unknown token category: 1 request(s)' in description
    assert 'Plan share USD: UNKNOWN' in description


def test_unpriced_and_missing_projections_do_not_emit_zero_dollars():
    result = sample(); group = result['costs']['groups'][0]
    group.update(known_usd='0', priced_tokens=0)
    text = cost.metrics(result)
    assert 'st_bead_api_equivalent_known_usd{' not in text
    assert 'st_bead_api_equivalent_usd{' not in text
    assert 'st_bead_priced_token_share{' in text
    assert 'API-equivalent USD: UNKNOWN' in cost.price_description({'groups': []}, 'task-a')


def test_complete_zero_is_distinct_from_missing_pricing():
    result = sample(); result['costs']['groups'][0].update(usd='0', known_usd='0', priced_tokens=100)
    assert 'st_bead_api_equivalent_usd{' in cost.metrics(result)
    assert '/ declared: 0;' in cost.price_description(result, 'task-a')


def test_codex_discovery_uses_durable_home_and_deduplicates_symlinks(tmp_path, monkeypatch):
    from shantytown import files, harness, cli
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path/'state'))
    card = SimpleNamespace(name='worker', workspace='/workspace/worker')
    monkeypatch.setattr(files.FilesRegistry, 'all', lambda _: SimpleNamespace(exact=lambda: [card]))
    monkeypatch.setattr(harness, 'for_card', lambda *a, **k: SimpleNamespace(name='codex'))
    path = tmp_path/'state/shantytown/codex/worker/sessions/2026/11/04/session.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'type':'session_meta','payload':{'cwd':card.workspace}})+'\n')
    settings = tmp_path/'settings'; settings.mkdir()
    (settings/'sessions').symlink_to(path.parents[3], target_is_directory=True)
    monkeypatch.setattr(cli, '_default_settings', lambda _: lambda _: str(settings/'config.toml'))
    got = cost.discover_sources(tmp_path)
    assert got == [{'agent':'worker','harness':'codex','path':str(path.resolve())}]
    path.write_text(json.dumps({'type':'session_meta','payload':{'cwd':'/another/workspace'}})+'\n')
    assert cost.discover_sources(tmp_path) == []
    monkeypatch.setattr(cli, '_default_settings', lambda _: lambda _: None)
    path.write_text(json.dumps({'type':'session_meta','payload':{'cwd':card.workspace}})+'\n')
    assert len(cost.discover_sources(tmp_path)) == 1


def test_daily_currency_joins_exact_request_identity_and_preserves_unknown():
    from shantytown import cost_daily
    from test_cost_daily import record, result, NOW
    measured = result(record(), record('two'))
    measured['costs'] = {'price_table_sha256': 'fixture-sha', 'records': [
        {'id':'one','session':'s','agent':'worker','harness':'claude','usd':'0.125'},
        {'id':'two','session':'s','agent':'worker','harness':'claude','usd':None}]}
    row = cost_daily.project(measured, now=NOW)[0]['rows'][0]
    assert row['api_equivalent'] == {'usd':None,'known_usd':'0.125',
        'priced_requests':1,'price_table_sha256':'fixture-sha'}
    assert row['requests'] == 2
    measured['costs']['records'][1]['usd'] = '0.375'
    row = cost_daily.project(measured, now=NOW)[0]['rows'][0]
    assert row['api_equivalent']['usd'] == '0.500'
    measured['costs']['records'][0]['agent'] = 'another-worker'
    row = cost_daily.project(measured, now=NOW)[0]['rows'][0]
    assert row['api_equivalent']['usd'] is None
    assert row['api_equivalent']['known_usd'] == '0.375'
