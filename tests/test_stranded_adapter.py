"""Real composition with synthetic registry, process, inbox and CAS boundaries."""
import copy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from shantytown.answer import Answer
from shantytown.files import FilesRegistry
from shantytown.inbox import FilesInbox
from shantytown.owned_work import OwnedWork
from shantytown.protocols import Agent
from shantytown.stopped import FilesStops
from shantytown.stranded_adapter import sweep


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('SHANTY_STRANDED_WORK', 'observe')
    monkeypatch.setattr('shantytown.deployment.local_host', lambda _: 'test-host')
    cards = {
        'worker': Agent('worker', 'worker', reports_to='lead', pane='worker', host='test-host'),
        'lead': Agent('lead', 'lead', reports_to='admin', pane='lead', host='test-host'),
        'admin': Agent('admin', 'administrator', pane='admin', host='test-host'),
        'remote': Agent('remote', 'worker', pane='remote', host='other-host'),
    }
    registry = SimpleNamespace(all=lambda: Answer.complete_read(list(cards.values()), how='fixture'),
                               get=lambda name: cards[name])
    row = dict(id='work-1', assignee='worker', status='in_progress', priority=0, title='work', labels=[])
    tracker = SimpleNamespace(stranded_rows=lambda owners: [dict(row)])
    states = dict(worker='down', lead='down', admin='live', remote='down')
    panes = SimpleNamespace(owner_state=lambda pane: states[pane])
    inbox = FilesInbox(tmp_path / 'inbox')
    return SimpleNamespace(root=tmp_path, cards=cards, registry=registry, tracker=tracker,
                           row=row, states=states, panes=panes, inbox=inbox)


def run(world, now=0):
    return sweep(world.root, world.registry, world.tracker, world.panes, world.inbox, now=now)


def test_error_routes_past_down_lead_and_persistent_held_reader_fact(setup):
    run(setup)
    assert not setup.inbox.unread('admin')
    run(setup, 3601)
    messages = setup.inbox.unread('admin')
    assert len(messages) == 1 and 'work-1' in messages[0].body
    state = OwnedWork(setup.root).snapshot()['worker']
    assert state['state'] == 'stopped' and state['graph_observed_at'] == 3601
    from shantytown.owned_work_graph import fact
    _, payload, _ = fact('worker', state, 'https://example.test/ontology/', 'test-source')
    assert json.loads(payload)['state'] == 'stopped'
    run(setup, 3610)
    assert len(setup.inbox.unread('admin')) == 1
    setup.states['worker'] = 'live'
    run(setup, 3620)
    assert OwnedWork(setup.root).snapshot()['worker']['state'] == 'live'


@pytest.mark.parametrize('host', [None, 'other-host'])
def test_foreign_or_unscoped_owner_is_unknown_never_down(setup, host):
    setup.cards['worker'] = replace(setup.cards['worker'], host=host)
    assert run(setup) == [('work-1', 'owner liveness UNKNOWN')]
    assert not setup.inbox.unread('admin')
    assert OwnedWork(setup.root).snapshot() == {}


def test_intent_resume_keeps_owner_and_no_brief_attention(setup):
    FilesStops(setup.root / 'stopped').record('worker', 0, resume_at='2999-01-01T00:00:00Z')
    assert ('work-1', 'needs attention') in run(setup)
    assert len(setup.inbox.unread('admin')) == 1
    assert OwnedWork(setup.root).snapshot() == {}


def test_malformed_stop_store_refuses_not_an_absent_hold(setup):
    directory = setup.root / 'stopped'
    directory.mkdir()
    (directory / 'worker.json').write_text('{broken')
    with pytest.raises(Exception, match='unreadable'):
        run(setup)
    assert not setup.inbox.unread('admin')


def test_release_mode_requires_actual_revision_adapter(setup, monkeypatch):
    monkeypatch.setenv('SHANTY_STRANDED_WORK', 'release')
    with pytest.raises(ValueError, match='revision-fenced'):
        run(setup)


def test_unknown_host_refuses_before_board_read(setup, monkeypatch):
    monkeypatch.setattr('shantytown.deployment.local_host', lambda _: None)
    with pytest.raises(ValueError, match='host scope UNKNOWN'):
        run(setup)


def test_dated_stop_roundtrip_and_legacy_compatibility(tmp_path):
    store = FilesStops(tmp_path)
    store.record('new', 1, reason='resume later', resume_at='2027-01-01T00:00:00Z')
    store.record('old', 1, reason='old record')
    assert store.get('new').resume_at == '2027-01-01T00:00:00Z'
    assert store.get('old').resume_at is None


def test_invalid_resume_date_refuses_before_stop_mutation(monkeypatch, tmp_path):
    from shantytown import cli
    monkeypatch.setattr(cli, '_stop_locked', lambda _: pytest.fail('stop mutated'))
    args = SimpleNamespace(resume_at='not-a-date', root=tmp_path, agent='worker', dry_run=False)
    assert cli._cmd_stop(args) == 2


def test_lifecycle_lock_reentrant_and_serializes_other_thread(tmp_path):
    from shantytown.cycle import lifecycle_lock
    from threading import Event, Thread
    entered, waiting = Event(), Event()
    def other():
        waiting.set()
        with lifecycle_lock(tmp_path, 'worker'):
            entered.set()
    with lifecycle_lock(tmp_path, 'worker'):
        with lifecycle_lock(tmp_path, 'worker'):
            thread = Thread(target=other)
            thread.start()
            assert waiting.wait(2)
            assert not entered.wait(.05)
    thread.join(2)
    assert entered.is_set() and not thread.is_alive()


def test_every_real_launch_takes_lifecycle_lock_before_admission(monkeypatch, tmp_path):
    from shantytown import cli
    from contextlib import contextmanager
    events = []
    @contextmanager
    def locked(root, name):
        events.append('lock')
        yield
        events.append('unlock')
    monkeypatch.setattr(cli.cycle_mod, 'lifecycle_lock', locked)
    monkeypatch.setattr(cli, '_launch_locked', lambda *a, **kw: events.append('admission') or 0)
    assert cli._launch(SimpleNamespace(root=tmp_path), setup_card := Agent('worker', 'worker'),
                       None, None) == 0
    assert events == ['lock', 'admission', 'unlock']
    events.clear()
    assert cli._launch(SimpleNamespace(root=tmp_path), setup_card, None, None, dry_run=True) == 0
    assert events == ['admission']


def test_undated_operator_stop_has_immediate_attention_in_observe(setup):
    FilesStops(setup.root / 'stopped').record('worker', 0, reason='operator hold')
    assert ('work-1', 'needs attention') in run(setup)
    assert ('work-1', 'needs attention') in run(setup, 100000)
    assert len(setup.inbox.unread('admin')) == 1
    assert OwnedWork(setup.root).snapshot() == {}


def test_positive_cycle_refusal_uses_measured_hour_even_with_live_pane(setup):
    from shantytown.cycle import Requests
    path = Requests(setup.root).path
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'worker': {'requested_at': 0,
        'refused': {'reason': 'fixture dirty tree', 'paths': ['fixture']}}}))
    setup.states['worker'] = 'live'
    run(setup)
    run(setup, 3600)
    assert not setup.inbox.unread('admin')
    run(setup, 3601)
    assert len(setup.inbox.unread('admin')) == 1
    assert 'cycle refusal' in OwnedWork(setup.root).snapshot()['worker']['reason']
    path.write_text('{}')
    run(setup, 3610)
    assert OwnedWork(setup.root).snapshot()['worker']['state'] == 'live'


def test_malformed_cycle_ledger_is_unknown(setup):
    from shantytown.cycle import Requests
    path = Requests(setup.root).path
    path.parent.mkdir(parents=True)
    path.write_text('{malformed')
    assert run(setup) == [('work-1', 'owner liveness UNKNOWN')]
    assert run(setup, 9000) == [('work-1', 'owner liveness UNKNOWN')]
    assert not setup.inbox.unread('admin')


def test_complete_assignee_census_counts_300_parked_work_and_skips_inbox(setup):
    rows = [dict(setup.row, id=f'work-{i}', status='deferred',
                 defer_until='2999-01-01T00:00:00Z', labels=['blocked:external'],
                 title='parked work') for i in range(300)]
    rows += [dict(setup.row, id=f'message-{i}', title='inbox: preserved') for i in range(241)]
    scopes = []
    def census(owners):
        scopes.append(owners)
        return copy.deepcopy(rows)
    setup.tracker.stranded_rows = census
    setup.tracker.ranking_rows = lambda: pytest.fail('ranking is not a complete assignee census')
    FilesStops(setup.root / 'stopped').record('worker', 0, reason='operator hold')
    run(setup, 10)
    findings = json.loads((setup.root / 'stranded-work/attention.json').read_text())
    assert len(findings) == 300
    assert all(row['release_due'] and row['evidence'] == 'operator-stopped'
               for row in findings.values())
    proof = json.loads((setup.root / 'stranded-work/census.json').read_text())
    assert proof['complete'] is True
    assert proof['owners']['worker'] == dict(work=300, release_due=300)
    assert proof['inbox_pointers'] == 'not read; never release candidates'
    assert scopes == [['admin', 'lead', 'worker']]


@pytest.mark.parametrize('state', ['live', 'unknown'])
def test_stop_record_cannot_promote_live_or_unknown_process(setup, state):
    setup.states['worker'] = state
    FilesStops(setup.root / 'stopped').record('worker', 0, reason='operator hold')
    run(setup, 10)
    findings = json.loads((setup.root / 'stranded-work/attention.json').read_text())
    assert not any(row.get('release_due') for row in findings.values())
    assert not setup.inbox.unread('admin')


def test_release_mode_keeps_non_operator_classes_observe(setup, monkeypatch):
    monkeypatch.setenv('SHANTY_STRANDED_WORK', 'release')
    setup.row['status'] = 'open'
    setup.tracker.stranded_read = lambda _: copy.deepcopy(setup.row)
    setup.tracker.release_stranded = lambda *_: pytest.fail('unadmitted class released')
    run(setup, 0)
    run(setup, 3601)
    assert len(setup.inbox.unread('admin')) == 1
    findings = json.loads((setup.root / 'stranded-work/attention.json').read_text())
    assert findings['work-1']['attention']
    assert findings['work-1']['release_due'] is False


@pytest.mark.parametrize('ledger', ['{malformed', '{"worker":{"refused":{"reason":"old refusal","paths":[]}}}'])
def test_operator_stop_and_process_absence_are_not_hidden_by_old_cycle_ledger(setup, ledger):
    from shantytown.cycle import Requests
    path = Requests(setup.root).path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ledger)
    FilesStops(setup.root / 'stopped').record('worker', 0)
    run(setup, 10)
    finding = json.loads((setup.root / 'stranded-work/attention.json').read_text())['work-1']
    assert finding['evidence'] == 'operator-stopped' and finding['release_due']


def test_stopped_administrator_cannot_receive_release_prerequisite(setup):
    setup.states['admin'] = 'down'
    FilesStops(setup.root / 'stopped').record('worker', 0)
    result = run(setup, 10)
    assert ('work-1', 'administrator route UNKNOWN; no release') in result
    assert not setup.inbox.unread('admin')


def test_natural_clock_census_matches_current_attention(setup):
    """The scheduled caller omits now; its coverage count must still be honest."""
    FilesStops(setup.root / 'stopped').record('worker', 0, reason='operator hold')
    assert ('work-1', 'needs attention') in sweep(
        setup.root, setup.registry, setup.tracker, setup.panes, setup.inbox)
    findings = json.loads((setup.root / 'stranded-work/attention.json').read_text())
    census = json.loads((setup.root / 'stranded-work/census.json').read_text())
    assert findings['work-1']['release_due'] is True
    assert census['checked_at'] == findings['work-1']['checked_at']
    assert census['owners']['worker'] == dict(work=1, release_due=1)


def test_whole_harness_stopped_releases_every_owned_item_in_one_pass(setup, monkeypatch):
    """aegis-byt fixture: a whole harness at 0 live, 32 assigned items.

    One tend pass must leave 0 items assigned to the stopped crew. In-progress
    work returns to open; deferred and blocked work keeps its status and its
    deferral; inbox pointers and a live owner's work are untouched. The admin
    gets ONE keyed notice per stopped owner, not one per item.
    """
    monkeypatch.setenv('SHANTY_STRANDED_WORK', 'release')
    monkeypatch.setattr('shantytown.stranded_adapter.checkpoint', lambda card: dict(
        worktree='/kept/' + card.name, branch='kept', head='0' * 40, checkpoint='kept'))
    harness = ['c1', 'c2', 'c3', 'c4', 'c5', 'c6']
    for name in harness:
        setup.cards[name] = Agent(name, 'worker', reports_to='lead', pane=name, host='test-host')
        setup.states[name] = 'down'
        FilesStops(setup.root / 'stopped').record(name, 0)  # undated operator stop
    setup.cards['alive'] = Agent('alive', 'worker', reports_to='lead', pane='alive', host='test-host')
    setup.states['alive'] = 'live'
    statuses = ['open', 'in_progress', 'deferred', 'blocked']
    store = {}
    for i in range(32):
        status = statuses[i % 4]
        store[f'work-{i}'] = dict(id=f'work-{i}', assignee=harness[i % 6], status=status,
            priority=i % 3, title='work', labels=[], revision=1,
            defer_until='2999-01-01T00:00:00Z' if status == 'deferred' else None)
    for i, extra in enumerate([dict(title='ASK Stiwi: decide'), dict(labels=['desk']),
                               dict(labels=['needs-stiwi'], status='deferred')]):
        store[f'ask-{i}'] = dict(dict(id=f'ask-{i}', assignee=harness[i], status='open', priority=0,
            title='decision', labels=[], revision=1), **extra)
    for row in store.values():
        row['notes'] = 'checkpoint: ' + row['id']
    comments = {}
    store['message-1'] = dict(id='message-1', assignee='c1', status='open', priority=2,
                              title='inbox: pointer', labels=[], revision=1)
    store['live-1'] = dict(id='live-1', assignee='alive', status='open', priority=0,
                           title='work', labels=[], revision=1)
    before = copy.deepcopy(store)
    def release(row, comment, *, operator_stopped=False):
        current = store[row['id']]
        assert operator_stopped and current['revision'] == row['revision']
        comments[row['id']] = json.loads(comment)
        current.update(assignee='', revision=current['revision'] + 1,
                       status='open' if current['status'] == 'in_progress' else current['status'])
        return 'released'
    setup.tracker.stranded_rows = lambda owners: [copy.deepcopy(r) for r in store.values()]
    setup.tracker.stranded_read = lambda identity: copy.deepcopy(store[identity])
    setup.tracker.release_stranded = release

    run(setup, 10)

    held = sorted(r['id'] for r in store.values()
                  if r['assignee'] in harness and not r['title'].startswith('inbox'))
    assert held == ['ask-0', 'ask-1', 'ask-2']  # ASK/desk class stays with its owner
    for identity, row in before.items():
        after = store[identity]
        assert after.get('notes') == row.get('notes')  # notes are never rewritten
        if identity.startswith('work-'):
            assert comments[identity]['original_owner'] == row['assignee']
            assert comments[identity]['worktree'] == '/kept/' + row['assignee']
        if identity in ('message-1', 'live-1') or identity.startswith('ask-'):
            assert after == row
        elif row['status'] == 'in_progress':
            assert after['status'] == 'open' and after['assignee'] == ''
        else:
            assert after['status'] == row['status'] and after['defer_until'] == row['defer_until']
    notices = setup.inbox.unread('admin')
    assert len(notices) == len(harness)
    assert all('operator-stopped' in n.body for n in notices)
    census = json.loads((setup.root / 'stranded-work/census.json').read_text())
    assert sum(c['work'] for n, c in census['owners'].items() if n in harness) == 35
    assert sum(c['release_due'] for n, c in census['owners'].items() if n in harness) == 32


def test_attention_notice_reads_back_as_delivered(setup):
    """Receipt readers match the marker at the START of the body (aegis-byt)."""
    run(setup, 0)
    run(setup, 3601)
    finding = json.loads((setup.root / 'stranded-work/attention.json').read_text())['work-1']
    assert finding['notice'] == 'delivered'
    message, = setup.inbox.unread('admin')
    assert message.body.startswith(finding['marker'] + ' ')


def test_operator_release_serves_priority_first_under_the_pass_cap(setup, monkeypatch):
    """With more release-due work than the cap, every P0/P1 item goes first."""
    monkeypatch.setenv('SHANTY_STRANDED_WORK', 'release')
    monkeypatch.setattr('shantytown.stranded_adapter.checkpoint', lambda card: dict(
        worktree='/kept', branch='kept', head='0' * 40, checkpoint='kept'))
    FilesStops(setup.root / 'stopped').record('worker', 0)
    store = {f'work-{i:03d}': dict(id=f'work-{i:03d}', assignee='worker', status='deferred',
             priority=4, title='parked', labels=[], revision=1) for i in range(60)}
    store.update({f'zz-hot-{i}': dict(id=f'zz-hot-{i}', assignee='worker', status='open',
                  priority=i % 2, title='work', labels=[], revision=1) for i in range(5)})
    def release(row, comment, *, operator_stopped=False):
        current = store[row['id']]
        current.update(assignee='', revision=current['revision'] + 1)
        return 'released'
    setup.tracker.stranded_rows = lambda owners: [copy.deepcopy(r) for r in store.values()]
    setup.tracker.stranded_read = lambda identity: copy.deepcopy(store[identity])
    setup.tracker.release_stranded = release
    run(setup, 10)
    assert all(store[f'zz-hot-{i}']['assignee'] == '' for i in range(5))
    assert sum(r['assignee'] == '' for r in store.values()) == 40  # the cap holds


def test_two_items_per_stopped_owner_both_release_through_the_real_sd_readback(setup, monkeypatch):
    """aegis-byt close fixture: the real SdTracker CAS + read-back, 2 items per owner.

    The first live pass released one item per owner and fenced each owner on a
    false UNKNOWN. Here both items of every owner release in ONE pass.
    """
    from shantytown.sd import SdTracker
    monkeypatch.setenv('SHANTY_STRANDED_WORK', 'release')
    monkeypatch.setattr('shantytown.stranded_adapter.checkpoint', lambda card: dict(
        worktree='/kept/' + card.name, branch='kept', head='0' * 40, checkpoint='kept'))
    owners = ['c1', 'c2', 'c3']
    for name in owners:
        setup.cards[name] = Agent(name, 'worker', reports_to='lead', pane=name, host='test-host')
        setup.states[name] = 'down'
        FilesStops(setup.root / 'stopped').record(name, 0)
    store = {}
    for i, name in enumerate(owners):
        store[f'{name}-a'] = dict(id=f'{name}-a', assignee=name, status='open', priority=1,
                                  title='work', labels=[], revision=3)
        store[f'{name}-b'] = dict(id=f'{name}-b', assignee=name, status='deferred', priority=2,
                                  title='parked', labels=['blocked:external'], revision=7,
                                  defer_until='2999-01-01T00:00:00Z')
    store['desk-1'] = dict(id='desk-1', assignee='c1', status='open', priority=1,
                           title='DESK: publish release - needs GO', labels=[], revision=2)
    comments = {k: [dict(text='older')] for k in store}
    def full(identity):
        r = dict(store[identity])
        return dict(r, comments=list(comments[identity]), comments_total=len(comments[identity]),
                    comments_folded=0, dependency_count=1, dependents=[], updated_at='t%d' % r['revision'])
    tracker = SdTracker(store='/synthetic/store', prefix='work')
    def sdk(identity, *args):
        if args[0] == 'show':
            return SimpleNamespace(returncode=0, stdout=json.dumps([full(identity)]))
        assert args[0] == 'update'
        flags = dict(a.split('=', 1) for a in args[2:] if a.startswith('--') and '=' in a)
        item = store[identity]
        if int(flags['--if-revision']) != item['revision']:
            return SimpleNamespace(returncode=4, stdout='')
        item.update(assignee=None, revision=item['revision'] + 1)
        if flags.get('--status'):
            item['status'] = flags['--status']
        comments[identity].append(dict(text=flags['--transition-comment']))
        return SimpleNamespace(returncode=0, stdout='{}')
    monkeypatch.setattr(tracker, '_bd_for', sdk)
    monkeypatch.setattr(tracker, '_use_remote_projection', lambda: True)
    setup.tracker = SimpleNamespace(
        stranded_rows=lambda names: [copy.deepcopy(r) for r in store.values() if r['assignee'] in names],
        stranded_read=tracker.stranded_read, release_stranded=tracker.release_stranded)

    result = run(setup, 10)

    assert not any('UNKNOWN' in f or 'unknown' in f for _, f in result), result
    for name in owners:
        assert store[f'{name}-a']['assignee'] is None and store[f'{name}-a']['status'] == 'open'
        assert store[f'{name}-b']['assignee'] is None and store[f'{name}-b']['status'] == 'deferred'
        assert store[f'{name}-b']['defer_until'] == '2999-01-01T00:00:00Z'
    assert store['desk-1']['assignee'] == 'c1'
    journal = json.loads((setup.root / 'stranded-work/release-intents.json').read_text())
    assert sorted(e['outcome'] for e in journal.values()) == ['released'] * 6
