"""Actual detector delay and notification delivery, with private-only seams."""
import json
from types import SimpleNamespace

import pytest

from shantytown import quiet_notice, quiet_time as quiet, quiet_detectors as detectors


def roster():
    cards = [SimpleNamespace(name=n, pane=n) for n in ['sattler', 'worker']]
    return SimpleNamespace(all=lambda: SimpleNamespace(exact=lambda: cards))


def test_signal_ends_lift_reaches_both_panes_by_180s(tmp_path, monkeypatch):
    (tmp_path / 'shantytown.toml').write_text('''
[[quiet_time.detector]]
name="media"
kind="process"
executable="private-fixture"
lift_delay=120
''')
    active = [True]
    monkeypatch.setitem(detectors.READERS, 'process', lambda *a: detectors.Signal(active[0]))
    reg, panes, sent = roster(), SimpleNamespace(exists=lambda p: True), []
    push = lambda r, p, n, text: sent.append((n, text)) or n
    run = lambda t: quiet_notice.sweep(tmp_path, quiet.probe(tmp_path, now=t),
                                      reg, panes, now=t, push=push, page=lambda *a: None)
    assert run(1000) == ['sattler', 'worker']
    active[0] = False
    assert run(1060) == []
    assert run(1120) == []
    assert run(1180) == ['sattler', 'worker']
    assert all('LIFTED' in text for _, text in sent[-2:])
    assert all('st fleet hold all --status' in text for _, text in sent[-2:])
    assert run(1240) == []


def test_failed_delivery_is_pending_then_retried_without_repeat(tmp_path):
    reg, panes = roster(), SimpleNamespace(exists=lambda p: True)
    held = quiet.Status((('media', quiet.Observation('active')),))
    receipt = []
    def push(r, p, name, text):
        receipt.append(name)
        return name if name == 'sattler' or receipt.count(name) > 1 else None
    run = lambda: quiet_notice.sweep(tmp_path, held, reg, panes, now=1000, push=push)
    assert run() == ['sattler']
    assert json.loads((tmp_path/'notify/quiet_time_delivery.json').read_text())['pending'] == ['worker']
    assert run() == ['worker']
    assert run() == []
    assert receipt == ['sattler', 'worker', 'worker']


def test_prolonged_hold_and_failed_slowdown_page_without_clearing(tmp_path):
    reg, panes, pages = roster(), SimpleNamespace(exists=lambda p: True), []
    held = quiet.Status((('media', quiet.Observation('active')),))
    page = lambda r, p, text: pages.append(text) or 'sattler'
    run = lambda t, **kw: quiet_notice.sweep(tmp_path, held, reg, panes, now=t,
        push=lambda *a: 'ok', page=page, **kw)
    run(1000)
    run(2799)
    assert pages == []
    run(2800)
    run(2860)
    assert len(pages) == 1 and '30 minutes' in pages[0]
    run(2920, slowdown_unknown=True)
    run(2980, slowdown_unknown=True)
    assert len(pages) == 2 and 'provenance' in pages[1]
    assert held.held


def test_initial_clear_silent_unknown_page_retries_and_corruption_refuses(tmp_path):
    reg, panes, pages = roster(), SimpleNamespace(exists=lambda p: True), []
    clear = quiet.Status((('media', quiet.Observation('clear')),))
    kwargs = dict(push=lambda *a: 'ok', page=lambda *a: pages.append(a[-1]) or None)
    assert quiet_notice.sweep(tmp_path, clear, reg, panes, **kwargs) == []
    unknown = quiet.Status((('media', quiet.Observation('unknown')),))
    quiet_notice.sweep(tmp_path, unknown, reg, panes, **kwargs)
    quiet_notice.sweep(tmp_path, unknown, reg, panes, **kwargs)
    assert len(pages) == 2
    (tmp_path/'notify/quiet_time_delivery.json').write_text('broken')
    with pytest.raises(ValueError):
        quiet_notice.sweep(tmp_path, clear, reg, panes, **kwargs)


def test_clear_peer_does_not_hide_unknown_and_journal_failure_sends_nothing(tmp_path, monkeypatch):
    reg, panes, pages = roster(), SimpleNamespace(exists=lambda p: True), []
    mixed = quiet.Status((('media', quiet.Observation('clear')),
                          ('gaming', quiet.Observation('unknown'))))
    assert mixed.state == 'clear'
    quiet_notice.sweep(tmp_path, mixed, reg, panes, push=lambda *a: 'ok',
                       page=lambda *a: pages.append(a[-1]) or 'sattler')
    assert len(pages) == 1
    sent = []
    monkeypatch.setattr(quiet_notice, 'write_json_atomic',
                        lambda *a: (_ for _ in ()).throw(OSError('fixture journal unavailable')))
    with pytest.raises(OSError):
        quiet_notice.sweep(tmp_path, quiet.Status((('media', quiet.Observation('active')),)),
                           reg, panes, push=lambda *a: sent.append(a) or 'ok')
    assert sent == []


def test_upgrade_from_legacy_hold_announces_lift_without_old_ledger_mutation(tmp_path):
    folder = tmp_path/'notify'
    folder.mkdir()
    legacy = folder/'gaming_hold.json'
    raw = '{"local":{"key":"held:media","risk":0,"failure":false}}'
    legacy.write_text(raw)
    clear = quiet.Status((('media', quiet.Observation('clear')),))
    seen = []
    assert quiet_notice.sweep(tmp_path, clear, roster(), SimpleNamespace(exists=lambda p: True),
        push=lambda r, p, name, text: seen.append(text) or name) == ['sattler', 'worker']
    assert all('LIFTED' in text for text in seen)
    assert legacy.read_text() == raw


def test_upgrade_still_held_starts_prolonged_hold_clock(tmp_path):
    (tmp_path/'notify').mkdir()
    (tmp_path/'notify/gaming_hold.json').write_text('{"local":{"key":"held:media"}}')
    held = quiet.Status((('media', quiet.Observation('active')),))
    pages = []
    run = lambda t: quiet_notice.sweep(tmp_path, held, roster(),
        SimpleNamespace(exists=lambda p: True), now=t, push=lambda *a: 'ok',
        page=lambda *a: pages.append(a[-1]) or 'sattler')
    assert run(1000) == ['sattler', 'worker']
    run(2800)
    assert len(pages) == 1


def test_pending_delivery_metric_retains_failures_and_corruption(tmp_path):
    assert 'notice_pending 0\n' in quiet_notice.metrics(tmp_path)
    held = quiet.Status((('media', quiet.Observation('active')),))
    quiet_notice.sweep(tmp_path, held, roster(), SimpleNamespace(exists=lambda p: True),
                       push=lambda *a: None)
    assert 'notice_pending 2\n' in quiet_notice.metrics(tmp_path)
    quiet_notice.sweep(tmp_path, held, roster(), SimpleNamespace(exists=lambda p: True),
                       push=lambda *a: 'ok')
    assert 'notice_pending 0\n' in quiet_notice.metrics(tmp_path)
    (tmp_path/'notify/quiet_time_delivery.json').write_text('broken')
    assert 'notice_pending 1\n' in quiet_notice.metrics(tmp_path)


@pytest.mark.parametrize("legacy_held", [True, False])
def test_actual_cli_first_clear_migrates_before_legacy_write(tmp_path, monkeypatch, legacy_held):
    from shantytown import cli, config, notify
    folder = tmp_path / 'notify'
    folder.mkdir()
    legacy = folder / 'gaming_hold.json'
    if legacy_held:
        legacy.write_text('{"local":{"key":"held:media","risk":0,"failure":false}}')
    clear = quiet.Status((('media', quiet.Observation('clear')),))
    reg, panes, sent = roster(), SimpleNamespace(exists=lambda p: True), []
    monkeypatch.setattr(config, 'load', lambda root: SimpleNamespace(quiet_time=SimpleNamespace(detectors=[])))
    monkeypatch.setattr(cli.quiet_time_mod, 'probe', lambda root: clear)
    monkeypatch.setattr(cli, '_registry', lambda a: reg)
    monkeypatch.setattr(cli, '_panes', lambda a: panes)
    monkeypatch.setattr(notify, 'push_to_own_pane', lambda r, p, n, text: sent.append((n, text)) or n)
    monkeypatch.setattr(notify, 'push_to_admin', lambda *a: pytest.fail('unexpected admin delivery'))
    args = SimpleNamespace(root=tmp_path, kind='all', metrics=None, slowdown=False,
                           probe=True, status=False, enable_detection=False,
                           disable_detection=False, clear=False)
    assert cli._cmd_hold(args) == 0
    assert len(sent) == (2 if legacy_held else 0)
    assert all('LIFTED' in text for _, text in sent)
    if legacy_held:
        assert json.loads(legacy.read_text())['local']['key'] == 'clear:'
    sent.clear()
    assert cli._cmd_hold(args) == 0
    assert sent == []


def test_actual_cli_journal_failure_retains_legacy_for_retry(tmp_path, monkeypatch):
    from shantytown import cli, config, notify
    (tmp_path / 'notify').mkdir()
    legacy = tmp_path / 'notify/gaming_hold.json'
    raw = '{"local":{"key":"held:media","risk":0,"failure":false}}'
    legacy.write_text(raw)
    clear = quiet.Status((('media', quiet.Observation('clear')),))
    reg, panes = roster(), SimpleNamespace(exists=lambda p: True)
    monkeypatch.setattr(config, 'load', lambda root: SimpleNamespace(quiet_time=SimpleNamespace(detectors=[])))
    monkeypatch.setattr(cli.quiet_time_mod, 'probe', lambda root: clear)
    monkeypatch.setattr(cli, '_registry', lambda a: reg)
    monkeypatch.setattr(cli, '_panes', lambda a: panes)
    monkeypatch.setattr(quiet_notice, 'write_json_atomic', lambda *a: (_ for _ in ()).throw(OSError('private journal failure')))
    monkeypatch.setattr(notify, 'push_to_own_pane', lambda *a: pytest.fail('unexpected pane delivery'))
    monkeypatch.setattr(cli, '_gaming_advisory', lambda *a: pytest.fail('legacy state must survive'))
    args = SimpleNamespace(root=tmp_path, kind='all', metrics=None, slowdown=False,
                           probe=True, status=False, enable_detection=False,
                           disable_detection=False, clear=False)
    assert cli._cmd_hold(args) == 0
    assert legacy.read_text() == raw


def test_a_lift_supersedes_the_stranded_hold_notice_custody(tmp_path):
    # aegis-185l: the hold body typed earlier must never be resent after a lift.
    from shantytown import delivery
    from shantytown.attribution import ST_TEND, attribute
    reg, panes = roster(), SimpleNamespace(exists=lambda p: True)
    held = quiet.Status((('media', quiet.Observation('active')),))
    sent = []
    push = lambda r, p, name, text: sent.append(text) or name
    quiet_notice.sweep(tmp_path, held, reg, panes, now=1000, push=push, page=lambda *a: None)
    hold = attribute(sent[-1], ST_TEND)
    with delivery.Custody(tmp_path, 'worker') as custody:
        custody.begin(hold, 17.0)
        custody.finish('queued')
        custody.record = None
        custody.begin('[from sattler] real mail', 17.0)
        custody.finish('queued')
    lifted = quiet.Status((('media', quiet.Observation('clear')),))
    quiet_notice.sweep(tmp_path, lifted, reg, panes, now=1060, push=push, page=lambda *a: None)
    assert 'LIFTED' in sent[-1]
    states = {json.loads(p.read_text())['text']: json.loads(p.read_text())['state']
              for p in (tmp_path / 'delivery').glob('send-*.json')}
    assert states == {hold: 'superseded', '[from sattler] real mail': 'queued'}
    assert quiet_notice.is_notice(hold) and not quiet_notice.is_notice('[from sattler] real mail')
