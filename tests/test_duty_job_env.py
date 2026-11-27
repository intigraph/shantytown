import json

import pytest

from shantytown.duty_discovery import job_bindings


@pytest.fixture(autouse=True)
def _legacy_timed_job_files(monkeypatch):
    # Fixtures use cron/every job files, which production now refuses
    # (tests/test_jobs_declare.py); these cases test duty binding, not timing.
    from shantytown import jobs
    monkeypatch.setattr(jobs, "LEGACY_TIMED_TRIGGERS", True)



def inventory(tmp_path, argv):
    jobs = tmp_path / 'jobs'
    jobs.mkdir()
    (jobs / 'example.toml').write_text(
        '[trigger]\nevery="1h"\n[action]\nexec = ' + json.dumps(argv) + '\n')
    return job_bindings(tmp_path, 'fixture-host')


def test_command_argument_is_not_an_assignment(tmp_path):
    assert inventory(tmp_path, ['env', '/usr/bin/printf', '%s',
                                'SHANTY_AGENT=worker']) == []


def test_leading_assignment_is_a_binding(tmp_path):
    rows = inventory(tmp_path, ['env', 'OTHER=value', 'SHANTY_AGENT=worker',
                                '/usr/bin/printf', 'SHANTY_AGENT=other'])
    assert [row['holder'] for row in rows] == ['worker']


@pytest.mark.parametrize('option', ['-i', '-u', '--unset=SHANTY_AGENT', '-S', '--'])
def test_unsupported_env_option_is_unknown(tmp_path, option):
    with pytest.raises(ValueError, match='unsupported env'):
        inventory(tmp_path, ['env', option, 'SHANTY_AGENT=worker', '/usr/bin/true'])
