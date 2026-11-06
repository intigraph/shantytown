"""Close failures retain the real child evidence, not just an observe warning."""
import json
from subprocess import CompletedProcess

import pytest

from shantytown import cli
from shantytown.br import BrTracker
from shantytown.sd import SdTracker
from shantytown.protocols import WorkItem


def invoke(tmp_path, monkeypatch, backend, stdout, stderr, code=1):
    tracker = backend()
    calls = []
    state = {'status': 'open', 'close_reason': None}

    def child(item_id, *args):
        calls.append(args)
        assert args[:3] == ('close', 'test-closed', '--json')
        if code == 0:
            state.update(status='closed', close_reason='measured proof')
        return CompletedProcess(args, code, stdout, stderr)

    monkeypatch.setattr(tracker, '_bd_for', child)
    monkeypatch.setattr(tracker, 'get', lambda item_id: WorkItem(item_id, **state))
    monkeypatch.setattr(cli, '_tracker', lambda args: tracker)
    reason = tmp_path / 'reason.txt'
    reason.write_text('measured proof')
    root = tmp_path / '.shanty'
    (root / 'crew').mkdir(parents=True)
    result = cli.main(['--root', str(root), 'work', 'item', 'close',
                       'test-closed', '--reason-file', str(reason)])
    return result, calls, state


@pytest.mark.parametrize('backend', [BrTracker, SdTracker])
@pytest.mark.parametrize('channel', ['stdout', 'stderr'])
def test_actual_close_cli_keeps_blocker_after_observe_warning(
        tmp_path, monkeypatch, capsys, backend, channel):
    warning = 'sd: actor/principal mismatch (observe): actor="worker" principal="fixture-principal" at="' + 'x' * 200 + '"\n'
    cause = 'cannot close test-closed: open blocker test-blocker'
    stdout = json.dumps({'error': {'code': 'OPEN_BLOCKER', 'message': cause}}) if channel == 'stdout' else ''
    stderr = warning + (cause if channel == 'stderr' else '')
    result, calls, state = invoke(tmp_path, monkeypatch, backend, stdout, stderr)
    assert result == 2 and len(calls) == 1 and state['status'] == 'open'
    error = json.loads(capsys.readouterr().err)['error']
    assert error['code'] == 'CLOSE_FAILED'
    assert error['details']['backend'] == backend._tool
    assert error['details']['exit_code'] == 1
    assert cause in error['details'][channel]
    assert 'observe' in error['details']['stderr']
    assert 'unproven' in error['message']


@pytest.mark.parametrize('backend', [BrTracker, SdTracker])
def test_empty_child_failure_still_names_transport_and_exit(tmp_path, monkeypatch, capsys, backend):
    result, calls, _ = invoke(tmp_path, monkeypatch, backend, '', '', code=7)
    assert result == 2 and len(calls) == 1
    error = json.loads(capsys.readouterr().err)['error']
    assert error['details'] == {'backend': backend._tool, 'exit_code': 7, 'stdout': '', 'stderr': ''}


def test_redaction_precedes_head_tail_bound(tmp_path, monkeypatch, capsys):
    token = 'fixture-private-secret-' * 200
    stderr = 'first evidence\nBearer ' + token + '\n' + 'padding ' * 700 + '\nfinal open blocker test-blocker'
    result, _, _ = invoke(tmp_path, monkeypatch, SdTracker, '', stderr)
    raw = capsys.readouterr().err
    assert result == 2 and 'fixture-private-secret' not in raw
    diagnostic = json.loads(raw)['error']['details']['stderr']
    assert diagnostic.startswith('first evidence') and diagnostic.endswith('final open blocker test-blocker')
    assert 'omitted' in diagnostic and len(diagnostic) < 2200


def test_observe_warning_does_not_turn_success_into_failure(tmp_path, monkeypatch, capsys):
    result, calls, state = invoke(tmp_path, monkeypatch, SdTracker, '{}', 'sd: actor/principal mismatch (observe)', code=0)
    assert result == 0 and len(calls) == 1 and state['status'] == 'closed'
    assert json.loads(capsys.readouterr().out)['result'] == 'verified'
