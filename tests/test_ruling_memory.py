"""Replay transcript attribution, successful receipts and once-per-state Stop."""
import io
import json
import shlex
from types import SimpleNamespace

import pytest

from shantytown import ruling_memory as rm, stop_policy as sp, stop_event

RULING = 'Stiwi ruling: Keep the change disabled by default.\nAbout: repo-example\nTopic: stop-advice'


def transcript(tmp_path, messages, codex=False, session='session-1'):
    path = tmp_path / 'transcript.jsonl'
    rows = ([dict(type='session_meta', payload=dict(id=session))] if codex else [])
    for role, content in messages:
        if codex:
            payload = content if role == 'tool' else dict(type='message', role=role, content=content)
            rows.append(dict(type='response_item', payload=payload))
        else:
            rows.append(dict(sessionId=session, message=dict(role=role, content=content)))
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    return dict(session_id=session, transcript_path=str(path))


@pytest.fixture
def armed(monkeypatch):
    monkeypatch.setenv('SHANTY_STOP_RULING_MEMORY', '1')


def test_off_by_default_does_not_read_transcript_or_write_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, 'pending', lambda _: pytest.fail('must not read'))
    assert rm.check(tmp_path, 'worker', {}) is None
    assert not (tmp_path / 'ruling-memory').exists()


@pytest.mark.parametrize('codex', [False, True])
def test_explicit_user_ruling_blocks_once_and_new_state_rearms(tmp_path, armed, codex):
    messages = [('user', RULING)]
    payload = transcript(tmp_path, messages, codex)
    first = rm.check(tmp_path, 'worker', payload)
    assert 'Held once' in first and 'cy record decision' in first
    command = next(line for line in first.splitlines() if line.startswith('cy '))
    args = shlex.split(command)
    assert args[:3] == ['cy', 'record', 'decision']
    assert args[args.index('--chose') + 1] == 'Keep the change disabled by default.'
    assert args[args.index('--about') + 1] == 'repo-example'
    assert args[args.index('--topic') + 1] == 'stop-advice'
    assert rm.check(tmp_path, 'worker', payload) is None
    messages.append(('assistant', 'More prose and a quoted ruling do not rearm.'))
    payload = transcript(tmp_path, messages, codex)
    assert rm.check(tmp_path, 'worker', payload) is None
    messages.append(('user', RULING.replace('disabled', 'enabled')))
    payload = transcript(tmp_path, messages, codex)
    assert rm.check(tmp_path, 'worker', payload)
    assert rm.check(tmp_path, 'worker', payload) is None


@pytest.mark.parametrize('role,text', [
    ('assistant', RULING), ('tool', RULING), ('user', '> ' + RULING),
    ('user', 'Documentation example:\n' + RULING),
    ('user', 'Stiwi might decide to use this.'), ('user', 'Stiwi said hello.'),
    ('user', 'Stiwi ruling: Should this be enabled?'),
])
def test_ambiguous_and_quoted_mentions_are_not_rulings(tmp_path, armed, role, text):
    assert rm.check(tmp_path, 'worker', transcript(tmp_path, [(role, text)])) is None


def test_missing_scope_is_explicit_not_invented_and_shell_quoted(tmp_path, armed):
    text = "Stiwi decided: Keep literal $(touch nope) and 'quoted' choices."
    reason = rm.check(tmp_path, 'worker', transcript(tmp_path, [('user', text)]))
    assert '${RULING_ABOUT:?' in reason and '${RULING_TOPIC:?' in reason
    command = next(line for line in reason.splitlines() if line.startswith('cy '))
    assert shlex.split(command)[4] == "Keep literal $(touch nope) and 'quoted' choices."
    assert "'Keep literal $(touch nope)" in command


def receipt_rows(output, call='write-1'):
    return [('assistant', [dict(type='tool_use', id=call, name='mcp__quipu__quipu_episode', input={})]),
            ('user', [dict(type='tool_result', tool_use_id=call, content=json.dumps(output))])]


@pytest.mark.parametrize('output', [dict(tx=23), dict(structuredContent=dict(tx_id=23)),
                                    dict(content=[dict(type='text', text='{"tx":23}')])])
def test_confirmed_paired_write_after_ruling_suppresses_reminder(tmp_path, armed, output):
    rows = [('user', RULING)] + receipt_rows(output)
    assert rm.check(tmp_path, 'worker', transcript(tmp_path, rows)) is None


@pytest.mark.parametrize('output', [dict(tx=0), dict(tx=23, isError=True),
                                    dict(result='queued'), dict(isError=False), dict(error='refused'),
                                    dict(tx=23, error='refused'), dict(tx=23, status='queued'),
                                    dict(tx=23, result='BLOCKED')])
def test_failed_queued_or_unconfirmed_write_does_not_satisfy(tmp_path, armed, output):
    assert rm.check(tmp_path, 'worker', transcript(tmp_path, [('user', RULING)] + receipt_rows(output)))


def test_old_write_and_unpaired_result_cannot_satisfy_new_ruling(tmp_path, armed):
    rows = receipt_rows(dict(tx=23)) + [('user', RULING)]
    rows += [('user', [dict(type='tool_result', tool_use_id='unknown', content='{"tx":42}')])]
    assert rm.check(tmp_path, 'worker', transcript(tmp_path, rows))


@pytest.mark.parametrize('status,output,satisfied', [
    (0, 'recorded decision https://example.org/decision\n', True),
    (0, 'unchanged https://example.org/decision\n', True),
    (0, 'queued 1\n', False), (1, 'recorded decision https://example.org/decision\n', False),
])
def test_codex_cli_pairs_exit_status_and_receipt(tmp_path, armed, status, output, satisfied):
    rows = [('user', RULING),
            ('tool', dict(type='function_call', call_id='c1', name='exec_command',
                          arguments=json.dumps(dict(cmd='cy record decision --chose choice')))),
            ('tool', dict(type='function_call_output', call_id='c1',
                          output=json.dumps(dict(exit_code=status, output=output))))]
    assert bool(rm.check(tmp_path, 'worker', transcript(tmp_path, rows, True))) is not satisfied


@pytest.mark.parametrize('damage', ['foreign', 'partial', 'oversize', 'malformed'])
def test_unknown_transcript_fails_open(tmp_path, armed, monkeypatch, damage):
    payload = transcript(tmp_path, [('user', RULING)])
    path = tmp_path / 'transcript.jsonl'
    if damage == 'foreign':
        payload['session_id'] = 'other'
    elif damage == 'partial':
        path.write_text(path.read_text() + '{')
    elif damage == 'oversize':
        monkeypatch.setattr(rm, 'MAX_BYTES', 10)
    else:
        path.write_text('not-json\n')
    assert rm.check(tmp_path, 'worker', payload) is None
    assert not (tmp_path / 'ruling-memory').exists()


def test_failed_durable_claim_never_blocks(tmp_path, armed, monkeypatch):
    monkeypatch.setattr(sp.P0Ledger, 'record', lambda *a: (_ for _ in ()).throw(OSError('readonly')))
    payload = transcript(tmp_path, [('user', RULING)])
    assert rm.check(tmp_path, 'worker', payload) is None
    assert rm.check(tmp_path, 'worker', payload) is None


def test_shared_stop_advice_uses_payload_once_and_retains_context_hint(tmp_path, armed, monkeypatch, capsys):
    from shantytown import context_hint
    payload = transcript(tmp_path, [('user', RULING)])
    seen = []
    monkeypatch.setattr(context_hint, 'emit', lambda root, card, **kw: seen.append(kw.get('payload')) or False)
    card = SimpleNamespace(name='worker')
    monkeypatch.setattr(sp.sys, 'stdin', io.StringIO(json.dumps(payload)))
    assert sp.stop_advice(tmp_path, card)
    assert json.loads(capsys.readouterr().out)['decision'] == 'block'
    monkeypatch.setattr(sp.sys, 'stdin', io.StringIO(json.dumps(payload)))
    assert not sp.stop_advice(tmp_path, card)
    assert seen == [payload]


def test_worker_haul_reaches_memory_check_before_board_work(tmp_path, armed, monkeypatch, capsys):
    payload = transcript(tmp_path, [('user', RULING)])
    monkeypatch.setattr(sp.sys, 'stdin', io.StringIO(json.dumps(payload)))
    class Registry:
        def get(self, _):
            return SimpleNamespace(name='worker')
    assert stop_event._haul(Registry(), object(), 'worker', tmp_path) == 0
    assert json.loads(capsys.readouterr().out)['decision'] == 'block'


@pytest.mark.parametrize('status', ['recorded', 'unchanged', 'superseded'])
def test_camayoc_structured_receipts_are_confirmed(tmp_path, armed, status):
    rows = [('user', RULING)] + receipt_rows(dict(structuredContent=dict(
        status=status, iri='https://example.org/decision')))
    assert rm.check(tmp_path, 'worker', transcript(tmp_path, rows)) is None


def test_session_identity_changes_rearm_without_persisting_ruling_text(tmp_path, armed):
    assert rm.check(tmp_path, 'worker', transcript(tmp_path, [('user', RULING)]))
    assert rm.check(tmp_path, 'worker', transcript(tmp_path, [('user', RULING)], session='new-session'))
    for path in (tmp_path / 'ruling-memory').rglob('*.json'):
        assert 'Keep the change' not in path.read_text()


def test_administrator_policy_run_reaches_memory_advice(tmp_path, armed, monkeypatch, capsys):
    payload = transcript(tmp_path, [('user', RULING)])
    monkeypatch.setattr(sp.sys, 'stdin', io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(sp, 'gather', lambda *a, **kw: pytest.fail('advice should precede gathering'))
    class Registry:
        def get(self, _):
            return SimpleNamespace(name='administrator')
    assert sp.run(tmp_path, 'administrator', reg=Registry()) == 0
    assert json.loads(capsys.readouterr().out)['decision'] == 'block'


def test_codex_mixed_session_is_unknown(tmp_path, armed):
    payload = transcript(tmp_path, [('user', RULING)], True)
    with (tmp_path / 'transcript.jsonl').open('a') as stream:
        stream.write(json.dumps(dict(type='session_meta', payload=dict(id='foreign'))) + '\n')
    assert rm.check(tmp_path, 'worker', payload) is None


def test_nonregular_transcript_never_blocks_on_open(tmp_path, armed):
    import os
    fifo = tmp_path / 'fifo'
    os.mkfifo(fifo)
    assert rm.check(tmp_path, 'worker', dict(session_id='session-1', transcript_path=str(fifo))) is None
