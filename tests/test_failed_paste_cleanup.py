"""An owned failed send may clear proved typed text, never opaque/foreign input."""
import json
from types import SimpleNamespace

import pytest

from shantytown import tmux, triage
from test_codex_0161_composer import frame

BODY = 'Owned first line\nOwned second line'


def failed_transport(monkeypatch, tmp_path, mode='owned'):
    panes = tmux.Tmux(root=tmp_path)
    state = dict(text='', entered=False, keys=[], runtime='original', session=17.0)
    monkeypatch.setattr(panes, 'foreground', lambda _: 'codex')
    monkeypatch.setattr(panes, 'runtime_identity', lambda _: state['runtime'])
    monkeypatch.setattr(panes, 'session_created', lambda _: state['session'])
    monkeypatch.setattr(tmux, '_journal_send', lambda *_: None)
    monkeypatch.setattr(tmux, '_CODEX_POLLS', 1)
    monkeypatch.setattr(tmux, '_CODEX_ATTEMPTS', 1)
    monkeypatch.setattr(tmux.time, 'sleep', lambda _: None)

    def capture(*a, **kw):
        if state['entered']:
            if mode == 'unreadable':
                raise OSError('unreadable fixture')
            if mode == 'foreign':
                return frame('Foreign draft')
            if mode == 'opaque':
                return frame(f'[Pasted Content {len(BODY)} chars]')
            if mode == 'busy':
                return 'Working (1s • esc to interrupt)\n' + frame(state['text'])
            if mode == 'queued':
                return '• Queued follow-up inputs\n  ↳ ' + BODY + '\n' + frame('')
        return frame(state['text'])

    def run(argv, **kw):
        if 'send-keys' in argv:
            if '-l' in argv:
                state['text'] += argv[-1]
            else:
                key = argv[-1]
                state['keys'].append(key)
                if key in ('Enter', 'Tab'):
                    state['entered'] = True
                    if mode == 'session':
                        state['session'] = 18.0
                    if mode == 'runtime':
                        state['runtime'] = 'replacement'
                elif key == 'C-u':
                    text = state['text']
                    state['text'] = text.rsplit('\n', 1)[0] + '\n' if '\n' in text else ''
                    if mode == 'race':
                        state['text'] = 'Foreign replacement'
                elif key == 'BSpace':
                    state['text'] = state['text'][:-1]
        return SimpleNamespace(stdout='0', returncode=0)

    monkeypatch.setattr(panes, 'capture', capture)
    monkeypatch.setattr(tmux.subprocess, 'run', run)
    return panes, state


def record(root):
    [path] = (root / 'delivery').glob('send-*.json')
    return json.loads(path.read_text())


def test_failed_owned_multiline_send_clears_before_unverified(monkeypatch, tmp_path):
    panes, state = failed_transport(monkeypatch, tmp_path)
    with pytest.raises(tmux.PaneSubmissionUnverified, match='UNVERIFIED'):
        panes.send('worker', BODY)
    assert state['text'] == ''
    assert triage.input_state(panes.capture('worker')) == triage.INPUT_EMPTY
    assert state['keys'] == ['Enter', 'C-e', 'C-u', 'BSpace', 'C-e', 'C-u']
    assert record(tmp_path)['state'] == 'cleared'
    assert not record(tmp_path).get('submission')
    assert record(tmp_path)['runtime'] == 'original'


@pytest.mark.parametrize('mode', ['foreign', 'opaque', 'busy', 'queued',
                                 'unreadable', 'session', 'runtime'])
def test_failed_send_does_not_edit_unproved_input(monkeypatch, tmp_path, mode):
    panes, state = failed_transport(monkeypatch, tmp_path, mode)
    with pytest.raises(tmux.PaneSubmissionUnverified):
        panes.send('worker', BODY)
    assert state['keys'] == ['Enter']
    assert record(tmp_path)['state'] != 'cleared'
    assert not record(tmp_path).get('submission')


def test_foreign_replacement_during_clear_stops_before_another_key(monkeypatch, tmp_path):
    panes, state = failed_transport(monkeypatch, tmp_path, 'race')
    with pytest.raises(tmux.PaneSubmissionUnverified):
        panes.send('worker', BODY)
    assert state['keys'] == ['Enter', 'C-e', 'C-u']
    assert state['text'] == 'Foreign replacement'
    assert record(tmp_path)['state'] == 'unknown'
