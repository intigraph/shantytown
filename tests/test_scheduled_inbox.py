"""Actual inbox persistence, with uncertainty that must never authorize replay."""
import json
import os

import pytest

from shantytown import cli, jobs, scheduled_inbox as child
from shantytown.inbox import FilesInbox


@pytest.fixture
def args(tmp_path, monkeypatch):
    (tmp_path / 'crew').mkdir()
    (tmp_path / 'crew' / 'receiver.json').write_text('{"role":"worker"}')
    monkeypatch.setenv('SHANTY_AGENT', 'scheduler')
    monkeypatch.setattr(jobs, 'load', lambda *a: pytest.fail('must not read job TOML'))
    return ['--root', str(tmp_path), '--backend', 'files', '--registry', 'files',
            '--sender', 'scheduler', '--recipient', 'receiver', '--job', 'pilot',
            '--message', 'run the synthetic watch']


def invoke(args, monkeypatch):
    read_fd, write_fd = os.pipe()
    try:
        monkeypatch.setenv(child.RESULT_FD_ENV, str(write_fd))
        code = child.main(args)
        os.close(write_fd)
        write_fd = None
        return code, os.read(read_fd, 4096)
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


def test_actual_persisted_pointer_and_attribution_precede_success(args, tmp_path, monkeypatch):
    code, raw = invoke(args, monkeypatch)
    assert (code, json.loads(raw)) == (0, dict(schema_version=1, outcome='succeeded', exit_code=0))
    message, = FilesInbox(tmp_path / 'inbox').unread('receiver')
    assert message.frm == 'scheduler'
    assert '[job pilot] run the synthetic watch' in message.body
    assert message.read is False, 'down recipient is persistence, not live delivery'


def test_missing_recipient_is_actual_refusal_not_success(args, monkeypatch):
    args[args.index('--recipient')+1] = 'absent'
    code, raw = invoke(args, monkeypatch)
    assert code == 1 and json.loads(raw)['outcome'] == 'failed'


def test_lost_response_after_actual_commit_is_unknown_without_retry(args, tmp_path, monkeypatch):
    original = FilesInbox.deliver
    attempts = []
    def lost(self, *a, **kw):
        attempts.append(1)
        original(self, *a, **kw)
        raise RuntimeError('synthetic response lost after commit')
    monkeypatch.setattr(FilesInbox, 'deliver', lost)
    code, raw = invoke(args, monkeypatch)
    assert code == 2 and raw == b'' and len(attempts) == 1
    assert len(FilesInbox(tmp_path / 'inbox').unread('receiver')) == 1


@pytest.mark.parametrize('result', [2, None, True, -1, 99])
def test_uncertain_or_invalid_cli_return_has_no_terminal_receipt(args, monkeypatch, result):
    calls = []
    monkeypatch.setattr(cli, 'main', lambda a: (calls.append(a), result)[1])
    code, raw = invoke(args, monkeypatch)
    assert code == 2 and raw == b'' and len(calls) == 1
    assert calls[0][:6] == args[:6]
    assert calls[0][-3:] == ['receiver', '-d', '[job pilot] run the synthetic watch']


@pytest.mark.parametrize('failure', [RuntimeError('lost'), SystemExit(1)])
def test_cli_exception_is_unknown(args, monkeypatch, failure):
    def fail(_):
        raise failure
    monkeypatch.setattr(cli, 'main', fail)
    assert invoke(args, monkeypatch) == (2, b'')


@pytest.mark.parametrize('fd', ['', '1', '2', '-1', 'garbage', '9999999999'])
def test_bad_descriptor_cannot_deliver(args, monkeypatch, fd):
    monkeypatch.setenv(child.RESULT_FD_ENV, fd)
    monkeypatch.setattr(cli, 'main', lambda _: pytest.fail('no action before result channel'))
    assert child.main(args) == 2


def test_regular_file_and_read_end_are_not_result_channels(args, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, 'main', lambda _: pytest.fail('invalid channel'))
    with (tmp_path / 'not-a-pipe').open('wb') as f:
        monkeypatch.setenv(child.RESULT_FD_ENV, str(f.fileno()))
        assert child.main(args) == 2
    r, w = os.pipe()
    try:
        monkeypatch.setenv(child.RESULT_FD_ENV, str(r))
        assert child.main(args) == 2
    finally:
        os.close(r)
        os.close(w)


@pytest.mark.parametrize('flag,value', [('--root','relative'), ('--sender','other'),
    ('--recipient','-option'), ('--job','bad/name'), ('--message',' '), ('--message','x'*4097)])
def test_invalid_fixed_policy_refuses_before_action(args, monkeypatch, flag, value):
    args[args.index(flag)+1] = value
    monkeypatch.setattr(cli, 'main', lambda _: pytest.fail('invalid policy'))
    # Use an option-looking value as a single argparse assignment.
    if value == '-option':
        i = args.index(flag)
        args[i:i+2] = [flag+'='+value]
    assert invoke(args, monkeypatch) == (2, b'')


def test_missing_routing_is_not_guessed(args, monkeypatch):
    i = args.index('--backend')
    del args[i:i+2]
    monkeypatch.setattr(cli, 'main', lambda _: pytest.fail('no backend fallback'))
    with pytest.raises(SystemExit) as error:
        invoke(args, monkeypatch)
    assert error.value.code == 2


def test_lost_result_pipe_does_not_repeat_delivery(args, tmp_path, monkeypatch):
    r, w = os.pipe()
    os.close(r)
    try:
        monkeypatch.setenv(child.RESULT_FD_ENV, str(w))
        assert child.main(args) == 2
        assert len(FilesInbox(tmp_path / 'inbox').unread('receiver')) == 1
    finally:
        os.close(w)
