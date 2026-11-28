import copy
import os

import pytest

from shantytown.incident_executor import Executed, execute, frozen_digest
from shantytown.incident_report import Refusal
from tests.test_incident_consumer import FROZEN, envelope, files, refusals, report

SIGNER = 'alert-triage-signer'


@pytest.fixture
def journal(tmp_path):
    path = tmp_path / 'journal'
    path.mkdir(mode=0o700)
    return str(path)


class FakeBoard:
    def __init__(self):
        self.seeds = {}
        self.fail_create = False

    def find(self, key):
        return self.seeds.get(key, {}).get('id')

    def create(self, title, description, key):
        if self.fail_create:
            raise OSError('board down')
        self.seeds[key] = {'id': f'seed-{len(self.seeds) + 1}', 'title': title, 'description': description}
        return self.seeds[key]['id']


def signed(identity=SIGNER):
    return lambda record: identity


def go(journal, board, record=None, frozen=None, digest=None, spec=None, verify=signed(), expected=SIGNER):
    frozen = copy.deepcopy(FROZEN) if frozen is None else frozen
    return execute(report() if record is None else record, frozen=frozen,
                   frozen_sha256=frozen_digest(FROZEN) if digest is None else digest,
                   jobspec=spec or envelope(), journal=journal, verify=verify, expected_signer=expected, board=board)


def test_a_signed_verdict_creates_exactly_one_fix_seed_from_the_frozen_input(journal):
    board = FakeBoard()
    got = go(journal, board)
    assert isinstance(got, Executed) and not got.replay
    assert len(board.seeds) == 1
    seed = board.seeds[got.key]
    assert FROZEN['fingerprint'] in seed['title'] and FROZEN['item'] in seed['title']
    assert f'idempotency-key: {got.key}' in seed['description']
    assert f'onset {FROZEN["onset_utc"]}' in seed['description']


def test_a_replay_is_idempotent_and_creates_nothing_more(journal):
    board = FakeBoard()
    first, second = go(journal, board), go(journal, board)
    assert second.replay and second.seed_id == first.seed_id and len(board.seeds) == 1


def test_a_crash_after_create_before_the_record_is_recovered_by_key(journal):
    board = FakeBoard()
    first = go(journal, board)
    os.unlink(os.path.join(journal, 'executed-' + first.key + '.json'))
    again = go(journal, board)
    assert again.replay and again.seed_id == first.seed_id and len(board.seeds) == 1
    assert os.path.exists(os.path.join(journal, 'executed-' + first.key + '.json'))


@pytest.mark.parametrize('verify', [None, lambda r: None, lambda r: '', lambda r: 7,
                                    pytest.param(lambda r: (_ for _ in ()).throw(RuntimeError('bad sig')), id='raises')])
def test_an_unsigned_verdict_creates_no_seed_and_says_why(journal, verify):
    board = FakeBoard()
    assert go(journal, board, verify=verify) == Refusal('unsigned')
    assert board.seeds == {} and [r['reason'] for r in refusals(journal)] == ['unsigned']


def test_a_wrong_signer_creates_no_seed_and_says_why(journal):
    board = FakeBoard()
    assert go(journal, board, verify=signed('someone-else')) == Refusal('wrong-signer')
    assert board.seeds == {} and [r['reason'] for r in refusals(journal)] == ['wrong-signer']


def test_a_frozen_input_changed_since_launch_creates_no_seed(journal):
    board = FakeBoard()
    changed = dict(FROZEN, fingerprint='ffffffffffffffff')
    assert go(journal, board, frozen=changed) == Refusal('frozen-digest')
    assert board.seeds == {} and [r['reason'] for r in refusals(journal)] == ['frozen-digest']


def test_a_verdict_about_another_incident_creates_no_seed(journal):
    board = FakeBoard()
    other = dict(FROZEN, fingerprint='aaaaaaaaaaaaaaaa')
    got = go(journal, board, frozen=other, digest=frozen_digest(other))
    assert got == Refusal('incident-binding') and board.seeds == {}


def test_a_spec_that_routes_no_fix_creates_no_seed(journal):
    board = FakeBoard()
    spec = envelope()
    spec['resolved']['on'] = {v: [a for a in acts if a != 'file-followup'] for v, acts in spec['resolved']['on'].items()}
    import hashlib
    from shantytown.incident_report import _canonical
    spec['sha256'] = hashlib.sha256(_canonical(spec['resolved']).encode()).hexdigest()
    assert go(journal, board, spec=spec) == Refusal('no-fix-route') and board.seeds == {}


def test_a_board_fault_is_fatal_and_the_redelivery_creates_one_seed(journal):
    board = FakeBoard()
    board.fail_create = True
    with pytest.raises(OSError):
        go(journal, board)
    assert board.seeds == {} and not [f for f in files(journal) if f.startswith('executed-')]
    board.fail_create = False
    assert not go(journal, board).replay and len(board.seeds) == 1


def test_an_unsafe_journal_is_refused_without_touching_the_board(tmp_path):
    board = FakeBoard()
    path = tmp_path / 'open'
    path.mkdir(mode=0o777)
    os.chmod(path, 0o777)
    assert go(str(path), board) == Refusal('journal-dir') and board.seeds == {}


def test_no_launcher_signer_or_network_is_imported():
    import shantytown.incident_executor as mod
    text = open(mod.__file__).read()
    for word in ('subprocess', 'socket', 'urllib', 'requests', 'shuttle'):
        assert f'import {word}' not in text
