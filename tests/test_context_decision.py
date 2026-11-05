"""Real hook escalation and bounded judge failures; no production services."""
import json
import subprocess

import pytest

from shantytown import context_decision as cd, context_hint as ch, session_budget as sb
from shantytown.protocols import Agent


def setup(tmp_path, used=500, window=1000, native=False):
    (tmp_path / 'shantytown.toml').write_text('[session_budget]\ncontext_threshold_pct=50\n' +
        ('' if native else f'context_window={window}\n'))
    path = tmp_path / 'session.jsonl'
    if native:
        data = dict(type='event_msg', payload=dict(type='token_count', info=dict(
            last_token_usage=dict(input_tokens=used), model_context_window=window)))
    else:
        data = dict(message=dict(usage=dict(input_tokens=used)))
    path.write_text(json.dumps(data))
    return Agent('reader', role='administrator'), dict(session_id='one', transcript_path=str(path))


@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('window', [200000, 1000000])
def test_half_of_each_window_prompts_and_logs_without_judge(tmp_path, capsys, native, window):
    card, payload = setup(tmp_path, window // 2, window, native)
    assert ch.emit(tmp_path, card, payload)
    msg = json.loads(capsys.readouterr().out)['reason']
    assert '50%' in msg and 'checkpoint' in msg and 'st agent cycle --self' in msg
    row = json.loads((tmp_path / 'context-decisions.jsonl').read_text())
    assert row['decision'] == 'handoff' and 'UNKNOWN' in row['reason']
    assert row['situation']['percent'] == 50
    assert not ch.emit(tmp_path, card, payload)


def test_exception_is_bounded_and_hard_line_does_not_ask(tmp_path, monkeypatch, capsys):
    calls = []
    def judge(*args, **kwargs):
        calls.append(args)
        return dict(decision='continue', reason='finish the active change')
    monkeypatch.setattr(cd, 'judge', judge)
    card, payload = setup(tmp_path)
    assert ch.emit(tmp_path, card, payload)
    assert 'EXCEPTION' in json.loads(capsys.readouterr().out)['reason']
    assert not ch.emit(tmp_path, card, payload)
    ch.session_start(tmp_path, card, payload)
    assert not ch.emit(tmp_path, card, payload)
    setup(tmp_path, used=550)
    assert ch.emit(tmp_path, card, payload)
    assert len(calls) == 2
    setup(tmp_path, used=750)
    assert ch.emit(tmp_path, card, payload)
    assert 'HARD HANDOFF' in capsys.readouterr().out
    assert len(calls) == 2
    assert ch.emit(tmp_path, card, payload), 'hard limit cannot fall through to self-feed'
    rows = [json.loads(line) for line in (tmp_path / 'context-decisions.jsonl').read_text().splitlines()]
    assert rows[-1]['decision'] == 'handoff' and 'no Jev override' in rows[-1]['reason']


def test_keep_expires_by_time(tmp_path, monkeypatch):
    now = [10000]
    monkeypatch.setattr(ch.time, 'time', lambda: now[0])
    monkeypatch.setattr(cd, 'judge', lambda *a, **kw: dict(decision='continue', reason='short operation'))
    card, payload = setup(tmp_path)
    assert ch.emit(tmp_path, card, payload)
    now[0] += 601
    assert ch.emit(tmp_path, card, payload)


@pytest.mark.parametrize('hard', [49, 50, 81, True, float('nan')])
def test_invalid_hard_limit_refused(hard):
    with pytest.raises(sb.BudgetError):
        sb.parse(dict(context_threshold_pct=50, context_hard_pct=hard))


def test_judge_timeout_is_handoff_and_kills_process_group(monkeypatch):
    class Process:
        pid = 1234
        def communicate(self, data, timeout):
            assert timeout == cd.BUDGET_SECONDS
            raise subprocess.TimeoutExpired('judge', timeout)
        def wait(self):
            pass
    killed = []
    monkeypatch.setattr(cd.subprocess, 'Popen', lambda *a, **kw: Process())
    monkeypatch.setattr(cd.os, 'killpg', lambda *args: killed.append(args))
    result = cd.judge(dict(percent=55), 'fake-jev')
    assert result['decision'] == 'handoff' and 'UNKNOWN' in result['reason']
    assert killed and killed[0][0] == 1234


@pytest.mark.parametrize('choice,confidence,expected', [
    ('continue', .9, 'continue'), ('continue', .4, 'handoff'),
    ('handoff', .9, 'handoff'), ('none-of-these', .9, 'handoff'),
])
def test_real_jev_answer_shape_and_original_provenance(monkeypatch, choice, confidence, expected):
    class Client:
        def __init__(self, *a, **kw):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def call(self, tool, args):
            assert tool == 'jev_choice' and 'rebuild' in args['instructions']
            return dict(request='r', model='fixture-model', usage={},
                        answer=dict(choice=choice, confidence=confidence, probabilities={}))
    monkeypatch.setattr(cd, 'JevMCP', Client)
    result = cd.evaluate(dict(command='fixture', situation=dict(percent=55)))
    assert result['decision'] == expected
    assert result['verdict']['request'] == 'r'
    assert result['reason']


def test_configuration_change_rearms_even_with_a_keep_exception(tmp_path, monkeypatch):
    calls = []
    def judge(*args, **kwargs):
        calls.append(args)
        return dict(decision='continue', reason='short operation')
    monkeypatch.setattr(cd, 'judge', judge)
    card, payload = setup(tmp_path)
    assert ch.emit(tmp_path, card, payload)
    with (tmp_path / 'shantytown.toml').open('a') as f:
        f.write('context_hard_pct=70\n')
    assert ch.emit(tmp_path, card, payload)
    assert len(calls) == 2


def test_no_log_means_no_keep_exception(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cd, 'judge', lambda *a, **kw: dict(decision='continue', reason='short operation'))
    card, payload = setup(tmp_path)
    (tmp_path / 'context-decisions.jsonl').mkdir()
    assert ch.emit(tmp_path, card, payload)
    assert 'no exception granted' in json.loads(capsys.readouterr().out)['reason']
    assert not ch._load(ch._path(tmp_path, card)).get('exception')
