import copy
import json
import os
import stat

from pathlib import Path

import pytest

import shantytown.incident_consumer as consumer
from shantytown.incident_consumer import Consumed, consume, consume_event
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


EVENT = Path(__file__).parent / 'fixtures' / 'incident_consumer' / 'triage-event.json'


def event(raw, journal, frozen=None, spec=None):
    """Feed an event with the TRUSTED launch state, as the launcher would."""
    return consume_event(raw, frozen=copy.deepcopy(FROZEN) if frozen is None else frozen,
                         jobspec=spec or envelope(), journal=journal, verified=True)


def files(journal):
    return sorted(os.listdir(journal))


def intent_files(journal):
    return [f for f in files(journal) if not f.startswith('refusal-')]


def refusals(journal):
    return [json.loads(open(os.path.join(journal, f)).read()) for f in files(journal) if f.startswith('refusal-')]


def assert_refusal_recorded(journal, reason):
    """No intent record, and exactly one refusal record naming the reason."""
    assert intent_files(journal) == []
    assert [r['reason'] for r in refusals(journal)] == [reason]


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
    assert [r['reason'] for r in refusals(journal)] == ['run-rebound']


@pytest.mark.parametrize('flag', [False, None, 1, 'yes', 'True'])
def test_only_an_exactly_verified_record_is_read(journal, flag):
    assert run(journal, verified=flag) == Refusal('unverified-record')
    assert_refusal_recorded(journal, 'unverified-record')


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
    assert_refusal_recorded(journal, 'incident-binding')


@pytest.mark.parametrize('frozen', [
    {**FROZEN, 'extra': 1}, {k: v for k, v in FROZEN.items() if k != 'item'}, {**FROZEN, 'version': 2},
    {**FROZEN, 'item': ''}, None, [],
])
def test_a_malformed_frozen_input_is_refused(journal, frozen):
    assert consume(report(), frozen=frozen, jobspec=envelope(), journal=journal, verified=True) == Refusal('frozen-input')
    assert_refusal_recorded(journal, 'frozen-input')


def test_validator_refusals_pass_through_and_are_recorded(journal):
    partial = report()
    partial['report']['coverage'] = 'partial'
    assert run(journal, record=partial) == Refusal('invalid-report-or-spec')
    forged = envelope()
    forged['sha256'] = '0' * 64
    assert isinstance(run(journal, spec=forged), Refusal)
    assert intent_files(journal) == []
    recorded = refusals(journal)
    assert len(recorded) == 2 and recorded[0]['reason'] == 'invalid-report-or-spec'
    assert all(r['run_id'] == 'run-1' for r in recorded)


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
    assert consume_event(EVENT.read_bytes(), frozen=copy.deepcopy(FROZEN), jobspec=envelope(), journal=str(link), verified=True) == Refusal('journal-dir')
    assert os.listdir(target) == []
    assert sorted(os.listdir(open_dir)) == []


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
    assert imported == {'dataclasses', 'hashlib', 'json', 'os', 're', 'stat', 'tempfile', 'shantytown.incident_report'}


def test_the_same_refusal_twice_is_one_refusal_record(journal):
    assert run(journal, verified=False) == run(journal, verified=False) == Refusal('unverified-record')
    assert_refusal_recorded(journal, 'unverified-record')
    record = refusals(journal)[0]
    assert set(record) == {'version', 'kind', 'reason', 'record_sha256', 'frozen_sha256', 'jobspec_sha256', 'run_id'}
    assert 'Measured scope defect' not in open(os.path.join(journal, files(journal)[0])).read()


def test_a_replayed_recorded_event_is_one_intent_record(journal):
    raw = EVENT.read_bytes()
    first = event(raw, journal)
    again = event(raw, journal)
    assert isinstance(first, Consumed) and not first.replay
    assert again.replay and again.intents == first.intents
    assert [i.action for i in first.intents] == ['comment-item', 'file-followup']
    assert files(journal) == [os.path.basename(first.journal_path)]


@pytest.mark.parametrize('raw', [b'', b'not json', b'[]', b'{"kind":"incident_report"}',
                                 json.dumps({**json.loads(EVENT.read_bytes()), 'kind': 'other'}).encode(),
                                 b' ' * (consumer.RECORD_CAP + 1),
                                 # json.loads raises RecursionError here, not ValueError; under
                                 # the cap, so it once escaped as an unrecorded poison event.
                                 pytest.param(b'[' * 200000, id='deeply-nested')])
def test_a_malformed_event_is_refused_and_recorded(journal, raw):
    assert event(raw, journal) == Refusal('event-shape')
    assert_refusal_recorded(journal, 'event-shape')


@pytest.mark.parametrize('onset', ['2026-11-22T04:00:00.000Z', '2026-11-22T04:00:00.0Z'])
def test_an_equal_onset_spelled_differently_binds(journal, onset):
    raw = report()
    raw['report']['incident']['onset'] = onset
    assert isinstance(run(journal, record=raw), Consumed)


def test_onsets_that_differ_past_microseconds_do_not_bind(journal):
    raw = report()
    raw['report']['incident']['onset'] = '2026-11-22T04:00:00.0000001Z'
    assert run(journal, record=raw) == Refusal('incident-binding')


def test_a_garbage_record_at_the_final_path_refuses_unreadable(journal):
    first = run(journal)
    with open(first.journal_path, 'wb') as handle:
        handle.write(b'{truncated')
    assert run(journal) == Refusal('journal-unreadable')
    assert open(first.journal_path, 'rb').read() == b'{truncated'
    assert [r['reason'] for r in refusals(journal)] == ['journal-unreadable']


def test_an_oversized_record_is_refused_before_it_is_written(journal, monkeypatch):
    monkeypatch.setattr(consumer, 'RECORD_CAP', 64)
    assert run(journal) == Refusal('record-too-large')
    assert_refusal_recorded(journal, 'record-too-large')


def test_no_pending_files_survive_a_consume(journal):
    run(journal)
    run(journal, verified=False)
    assert not [f for f in files(journal) if f.startswith('.pending-')]


def test_the_fixture_event_carries_the_trusted_launch_state():
    """The tamper tests below are only meaningful if the untampered event matches."""
    stored = json.loads(EVENT.read_bytes())
    assert stored['frozen'] == FROZEN and stored['jobspec'] == envelope()


def _rehashed_spec(spec):
    """A forged spec that passes the validator's self-consistency check on its own."""
    import hashlib
    spec['sha256'] = hashlib.sha256(json.dumps(spec['resolved'], sort_keys=True, separators=(',', ':'),
                                               ensure_ascii=False).encode()).hexdigest()
    return spec


@pytest.mark.parametrize('tamper', [
    # Frozen rewritten to match a report about ANOTHER incident: self-attested binding.
    lambda e: e['frozen'].update(fingerprint='fedcba0987654321'),
    # Routes rewritten and rehashed so the spec is self-consistent: self-attested actions.
    lambda e: e.update(jobspec=_rehashed_spec({**e['jobspec'], 'resolved': {
        **e['jobspec']['resolved'], 'on': {**e['jobspec']['resolved']['on'], 'diagnosed': ['notify-owner']}}})),
])
def test_an_event_with_a_tampered_frozen_or_jobspec_is_refused(journal, tamper):
    forged = json.loads(EVENT.read_bytes())
    tamper(forged)
    if forged['jobspec'] != envelope():
        # Prove the forgery is one the validator alone would accept: only the trusted copy stops it.
        assert isinstance(consume(forged['record'], frozen=FROZEN, jobspec=forged['jobspec'],
                                  journal=journal, verified=True), Consumed)
        for name in files(journal):
            os.unlink(os.path.join(journal, name))
    assert event(json.dumps(forged).encode(), journal) == Refusal('launch-mismatch')
    assert_refusal_recorded(journal, 'launch-mismatch')
    entry = refusals(journal)[0]
    assert entry['event_frozen_sha256'] == consumer._digest(forged['frozen'])
    assert entry['event_jobspec_sha256'] == consumer._digest(forged['jobspec'])


def test_a_tampered_event_record_is_judged_against_the_trusted_frozen(journal):
    """Rewriting record AND frozen together must still fail: frozen comes from the caller."""
    forged = json.loads(EVENT.read_bytes())
    forged['record']['report']['incident']['fingerprint'] = 'fedcba0987654321'
    assert event(json.dumps(forged).encode(), journal) == Refusal('incident-binding')
    forged['frozen']['fingerprint'] = 'fedcba0987654321'
    assert event(json.dumps(forged).encode(), journal) == Refusal('launch-mismatch')
    assert intent_files(journal) == []


def test_the_same_record_refused_under_two_specs_leaves_two_records(journal):
    first, second = envelope(), envelope()
    first['sha256'] = '0' * 64
    second['sha256'] = '1' * 64
    assert isinstance(run(journal, spec=first), Refusal) and isinstance(run(journal, spec=second), Refusal)
    recorded = refusals(journal)
    assert len(recorded) == 2 and len({r['jobspec_sha256'] for r in recorded}) == 2
    assert len({r['record_sha256'] for r in recorded}) == 1


@pytest.mark.parametrize('target', ['link', 'fsync'])
def test_a_journal_write_fault_is_fatal_not_dropped_and_redelivery_consumes_once(journal, monkeypatch, target):
    import errno
    real = getattr(os, target)

    def broken(*args, **kwargs):
        raise OSError(errno.ENOSPC, 'No space left on device')

    monkeypatch.setattr(os, target, broken)
    with pytest.raises(OSError):
        event(EVENT.read_bytes(), journal)
    with pytest.raises(OSError):
        run(journal, verified=False)  # a refusal that cannot be written raises too
    if target == 'link':
        assert files(journal) == []  # nothing half-written, no `.pending-*` leftover
    monkeypatch.setattr(os, target, real)
    got = event(EVENT.read_bytes(), journal)
    assert isinstance(got, Consumed) and not got.replay
    assert len(intent_files(journal)) == 1
    assert not [f for f in files(journal) if f.startswith('.pending-')]


def test_a_value_too_deep_to_serialize_or_repr_still_digests():
    class Deep(list):
        """Stands in for nesting deep enough that json.dumps and repr both recurse out."""
        def __repr__(self):
            raise RecursionError('maximum recursion depth exceeded')

    deep = Deep([object()])  # object() makes json.dumps fail, so the repr fallback runs
    assert consumer._digest(deep) == consumer._digest(Deep([object(), 1]))  # by type name, not a raise


def test_a_directory_fsync_fault_after_the_link_raises_and_redelivery_replays(journal, monkeypatch):
    import errno
    real_open = os.open

    def broken_open(path, flags, *args, **kwargs):
        if path == journal and flags == os.O_RDONLY:  # the directory fsync, after the link
            raise OSError(errno.EIO, 'Input/output error')
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, 'open', broken_open)
    with pytest.raises(OSError):
        event(EVENT.read_bytes(), journal)
    assert len(intent_files(journal)) == 1  # the link succeeded: the record is in place
    monkeypatch.setattr(os, 'open', real_open)
    got = event(EVENT.read_bytes(), journal)
    assert isinstance(got, Consumed) and got.replay
    assert [i.action for i in got.intents] == ['comment-item', 'file-followup']
    assert len(intent_files(journal)) == 1
