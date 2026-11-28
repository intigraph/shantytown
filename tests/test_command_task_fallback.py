import os

import pytest

from shantytown.query_identity import (
    TASK_COMMANDS, declared_command, read_headers, sdk_subprocess_options,
)


@pytest.fixture(autouse=True)
def absent_task(monkeypatch):
    monkeypatch.delenv('QUIPU_TASK', raising=False)
    monkeypatch.delenv('SEEDS_TASK', raising=False)


@pytest.mark.parametrize('read', [False, True])
def test_absent_task_uses_command_without_changing_process_environment(read):
    before = dict(os.environ)
    with declared_command('inbox'):
        assert read_headers()['X-Quipu-Task'] == 'st-inbox'
        options = sdk_subprocess_options(**({'read_operation': 'list'} if read else {}))
        assert options['env']['QUIPU_TASK'] == 'st-inbox'
    assert dict(os.environ) == before
    assert 'X-Quipu-Task' not in read_headers()


@pytest.mark.parametrize('key', ['QUIPU_TASK', 'SEEDS_TASK'])
@pytest.mark.parametrize('value', ['exact-work', 'invalid task', '', 'x' * 65])
def test_explicit_task_keeps_prior_valid_and_invalid_handling(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    before = read_headers().get('X-Quipu-Task')
    with declared_command('inbox'):
        assert read_headers().get('X-Quipu-Task') == before
        for options in (sdk_subprocess_options(), sdk_subprocess_options(read_operation='list')):
            env = options.get('env', os.environ)
            assert env.get(key) == value
            assert env.get('QUIPU_TASK') != 'st-inbox'
            if key == 'SEEDS_TASK':
                assert env['QUIPU_TASK'] == (before or '')


def test_unknown_registered_verbs_cannot_expand_fallback_vocabulary():
    observed = set()
    for n in range(1000):
        suffix = ''.join(chr(97 + digit) for digit in (n // 676, n // 26 % 26, n % 26))
        with declared_command('private_' + suffix, 'work', registered=True):
            assert read_headers()['X-Quipu-Source'] == 'st-work-private_' + suffix
            observed.add(read_headers()['X-Quipu-Task'])
    assert observed == {'st-other'}
    assert len(TASK_COMMANDS) <= 32
