import copy
import json
import os
import stat

import pytest

from shantytown.incident_consumer import Consumed, consume
from shantytown.incident_report import Refusal
from tests.test_incident_report import envelope, report

FROZEN = {'version': 1, 'item': 'item-1', 'fingerprint_kind': 'alertmanager-native',
          'fingerprint': '1234567890abcdef', 'onset_utc': '2026-11-22T04:00:00Z'}


@pytest.fixture
def journal(tmp_path):
    path = tmp_path / 'journal'
    path.mkdir(mode=0o700)
    return str(path)


def run(journal, record=None, frozen=None, spec=None, verified=True):
    return consume(report() if record is None else record, frozen=copy.deepcopy(FROZEN) if frozen is None else frozen,
                   jobspec=spec or envelope(), journal=journal, verified=verified)


def files(journal):
    return sorted(os.listdir(journal))


def test_verified_matching_report_journals_the_shadow_intents_once(journal):
    got = run(journal)
    assert isinstance(got, Consumed) and not got.replay
    assert [i.action for i in got.intents] == ['comment-item', 'file-followup']
    assert len(files(journal)) == 1
    mode = stat.S_IMODE(os.stat(got.journal_path).st_mode)
    assert mode == 0o600
    stored = json.loads(open(got.journal_path).read())
    assert [i['idempotency_key'] for i in stored['intents']] == [i.idempotency_key for i in got.intents]


def test_the_same_event_twice_is_one_record_and_the_same_intents(journal):
    first, second = run(journal), run(journal)
    assert second.replay and second.intents == first.intents
    assert files(journal) == [os.path.basename(first.journal_path)]


def test_the_same_run_with_a_changed_report_is_refused_and_the_record_is_kept(journal):
    first = run(journal)
    before = open(first.journal_path, 'rb').read()
    changed = report()
    changed['summary'] = 'A different conclusion'
    assert run(journal, record=changed) == Refusal('run-rebound')
    assert open(first.journal_path, 'rb').read() == before


@pytest.mark.parametrize('flag', [False, None, 1, 'yes', 'True'])
def test_only_an_exactly_verified_record_is_read(journal, flag):
    assert run(journal, verified=flag) == Refusal('unverified-record')
    assert files(journal) == []


@pytest.mark.parametrize('change', [
    lambda f: f.update(item='item-2'),
    lambda f: f.update(fingerprint='fedcba0987654321'),
    lambda f: f.update(onset_utc='2026-11-22T04:00:01Z'),
    lambda f: f.update(fingerprint_kind='escalation-bridge', fingerprint='123456789abc'),
])
def test_a_report_about_another_incident_is_refused(journal, change):
    frozen = copy.deepcopy(FROZEN)
    change(frozen)
    assert run(journal, frozen=frozen) == Refusal('incident-binding')
    assert files(journal) == []


@pytest.mark.parametrize('frozen', [
    {**FROZEN, 'extra': 1}, {k: v for k, v in FROZEN.items() if k != 'item'}, {**FROZEN, 'version': 2},
    {**FROZEN, 'item': ''}, None, [],
])
def test_a_malformed_frozen_input_is_refused(journal, frozen):
    assert consume(report(), frozen=frozen, jobspec=envelope(), journal=journal, verified=True) == Refusal('frozen-input')
    assert files(journal) == []


def test_validator_refusals_pass_through_and_write_nothing(journal):
    partial = report()
    partial['report']['coverage'] = 'partial'
    assert run(journal, record=partial) == Refusal('invalid-report-or-spec')
    forged = envelope()
    forged['sha256'] = '0' * 64
    assert isinstance(run(journal, spec=forged), Refusal)
    assert files(journal) == []


def test_an_unknown_verdict_has_no_intents_but_is_still_recorded(journal):
    raw = report()
    raw['verdict'] = 'unknown'
    raw['report']['coverage'] = 'unknown'
    got = run(journal, record=raw)
    assert isinstance(got, Consumed) and got.intents == ()
    assert len(files(journal)) == 1


def test_an_unsafe_journal_directory_is_refused(tmp_path):
    target = tmp_path / 'real'
    target.mkdir(mode=0o700)
    link = tmp_path / 'link'
    link.symlink_to(target)
    assert run(str(link)) == Refusal('journal-dir')
    open_dir = tmp_path / 'open'
    open_dir.mkdir()
    os.chmod(open_dir, 0o777)
    assert run(str(open_dir)) == Refusal('journal-dir')
    assert run(str(tmp_path / 'missing')) == Refusal('journal-dir')
    assert os.listdir(target) == []


def test_the_module_imports_nothing_that_could_execute_or_reach_out():
    import ast
    import shantytown.incident_consumer as module
    tree = ast.parse(open(module.__file__).read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported == {'dataclasses', 'hashlib', 'json', 'os', 'stat', 'tempfile', 'shantytown.incident_report'}
