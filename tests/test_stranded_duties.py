"""Exercise the existing sweep/stop boundary, not a second item detector."""
import copy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from shantytown import duty_adapter
from shantytown.duties import Duties, KINDS, SCHEMA, metrics, summary
from shantytown.files import write_json_atomic
from shantytown.stopped import FilesStops
from shantytown.stranded_adapter import sweep
from tests.test_stranded_adapter import setup

ROUTING_RULES = {'internal-landing': dict(repository_prefix='internal/',
                                        holder_rule='author', require_live=True)}


def record(ident='queue', *, binding='external', kind='merge-queue', priority=0):
    return dict(id=ident, holder='worker', binding=binding, kind=kind,
                priority=priority, source='fixture:configured-binding',
                candidates=['lead'], authors=[])


def install(world, rows):
    path = Duties(world.root).path
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, dict(schema=SCHEMA, revision=1,
                                coverage=list(KINDS), routing=ROUTING_RULES, entries=rows))


def armed(world, monkeypatch):
    monkeypatch.setenv('SHANTY_STRANDED_WORK', 'release')
    world.tracker.stranded_read = lambda _: copy.deepcopy(world.row)
    world.tracker.release_stranded = lambda *_a, **_k: pytest.fail('ASK must remain owned')
    world.row.update(title='ASK operator: retained decision', labels=['needs-stiwi'])
    world.states['lead'] = 'live'
    world.repairs = {}
    world.attempts = []

    def create(payload, *, target, key):
        world.attempts.append((copy.deepcopy(payload), target, key))
        world.repairs.setdefault(key, SimpleNamespace(id='repair-' + str(len(world.repairs))))
        return world.repairs[key]

    world.tracker.create_duty_issue = create
    return world


def run(world, at):
    return sweep(world.root, world.registry, world.tracker, world.panes, world.inbox, now=at)


def test_existing_sweep_rebinds_supported_duty_and_flags_reservation_once(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record(binding='registry'),
                    record('reserved-peer', kind='review-reservation')])
    FilesStops(world.root / 'stopped').record('worker', 0)
    result = run(world, 1800)
    assert ('queue', 'duty reassigned to lead') in result
    assert len(world.repairs) == 1 and len(world.attempts) == 1
    assert Duties(world.root).resolve('queue', live=lambda n: n == 'lead') == 'lead'
    assert world.row['assignee'] == 'worker'  # ASK exclusion survives composition.
    run(world, 2000)
    assert len(world.repairs) == 1 and len(world.attempts) == 1
    assert len(world.inbox.unread('admin')) == 1
    assert 'review-reservation"} 1' in metrics(world.root, now=2000)


@pytest.mark.parametrize('unavailable', [False, None, 'error'])
def test_failed_page_waits_for_live_admin_then_recovers_same_key(setup, unavailable):
    world = setup
    install(world, [dict(record('reserved-peer', kind='review-reservation'), candidates=[])])
    duty = Duties(world.root)
    available = True
    creations, pages = [], []

    def live(name):
        assert name == 'admin'
        if available == 'error':
            raise OSError('liveness unavailable')
        return available

    def create(payload, target, key):
        creations.append((copy.deepcopy(payload), target, key))
        return 'fixture-repair'

    def notify(target, message, key):
        pages.append((target, message, key))
        if len(pages) == 1:
            raise OSError('first page failed')

    def tick(now):
        return duty.tick(observe=lambda _: dict(state='operator-stopped', generation='stop-1', stopped_at=0),
                         live=live, administrator=lambda: 'admin', ensure_issue=create,
                         notify=notify, now=now, release=True)

    tick(1800)
    assert len(creations) == len(pages) == 1
    available = unavailable
    assert ('reserved-peer', 'duty page UNKNOWN') in tick(1801)
    state = json.loads((duty.root / 'attention.json').read_text())['reserved-peer']
    assert not state.get('paged') and state['repair'] == 'fixture-repair'
    assert len(creations) == len(pages) == 1
    available = True
    tick(1802)
    tick(1803)
    state = json.loads((duty.root / 'attention.json').read_text())['reserved-peer']
    assert state['paged'] is True
    assert len(creations) == 1 and len(pages) == 2
    assert creations[0][2] == pages[0][2] == pages[1][2]


def test_corrupt_duty_inventory_does_not_block_existing_item_sweep(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record()])
    Duties(world.root).path.write_text('{malformed')
    calls = []
    original = world.tracker.stranded_rows
    world.tracker.stranded_rows = lambda owners: (calls.append(owners) or original(owners))
    result = run(world, 1800)
    assert calls and ('duties', 'duty census UNKNOWN') in result
    assert 'UNKNOWN' in summary(world.root, now=1800)
    assert not world.repairs


def test_new_job_binding_is_discovered_and_retirement_preserves_manual_rows(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record('manual')])
    jobs = world.root / 'jobs'
    jobs.mkdir()
    source = jobs / 'daily.toml'
    source.write_text('[trigger]\nevery="1h"\n[action]\ninbox="worker"\nmessage="work"\n')
    FilesStops(world.root / 'stopped').record('worker', 0)
    run(world, 14400)
    rows = Duties(world.root).load()['entries']
    assert len(rows) == 2 and len(world.repairs) == 2
    generated = next(row for row in rows if row.get('producer') == 'local-jobs')
    assert generated['holder'] == 'worker' and generated['binding'] == 'external'
    source.unlink()
    run(world, 14500)
    assert [row['id'] for row in Duties(world.root).load()['entries']] == ['manual']


def test_bad_job_source_does_not_retire_previous_binding_or_block_items(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [dict(record('old-job'), producer='local-jobs')])
    jobs = world.root / 'jobs'
    jobs.mkdir()
    (jobs / 'bad.toml').write_text('bad=')
    assert ('duties', 'duty census UNKNOWN') in run(world, 1800)
    assert Duties(world.root).load()['entries'][0]['id'] == 'old-job'
    assert 'UNKNOWN' in summary(world.root, now=1800)


def test_unknown_remote_intent_keeps_exact_payload_across_owner_generation_change(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record()])
    FilesStops(world.root / 'stopped').record('worker', 0)
    attempts = []
    def lost(payload, *, target, key):
        attempts.append((copy.deepcopy(payload), target, key))
        if len(attempts) == 1:
            raise TimeoutError('committed reply lost')
        assert attempts[-1] == attempts[0]
        return SimpleNamespace(id='same-repair')
    world.tracker.create_duty_issue = lost
    run(world, 1800)
    row = record()
    row.update(holder='lead', source='fixture:new-binding')
    world.states['lead'] = 'down'
    FilesStops(world.root / 'stopped').record('lead', 0)
    duties = Duties(world.root)
    plan = dict(schema=SCHEMA, revision=1, coverage=list(KINDS), entries=[row])
    duties.install(plan, expected_revision=duties.load()['revision'], apply=True)
    run(world, 1801)
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert ('queue', 'repair same-repair') in run(world, 1802)


def test_managed_plan_checks_the_bytes_it_reads_not_an_earlier_path_probe(tmp_path):
    import hashlib
    from shantytown.duties import _read
    path = tmp_path / 'plan.json'
    raw = b'{"same":"value"}\n'
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    assert _read(path, expected_sha256=digest) == {'same': 'value'}
    path.write_bytes(raw + b' ')
    with pytest.raises(ValueError, match='reviewed digest'):
        _read(path, expected_sha256=digest)
    with pytest.raises(ValueError, match='reviewed digest'):
        _read(path, expected_sha256='invalid')


def test_one_sweep_recovers_item_duty_and_reservation_then_explicit_stop_preserves_ask(setup, monkeypatch):
    from shantytown import cli, stranded_adapter
    world = armed(setup, monkeypatch)
    world.row.update(title='ordinary work', labels=[], revision=1)
    decision = dict(world.row, id='ask-1', title='ASK operator: retained', labels=['needs-stiwi'])
    world.tracker.stranded_rows = lambda _: copy.deepcopy([world.row, decision])
    world.tracker.stranded_read = lambda ident: copy.deepcopy(world.row if ident == world.row['id'] else decision)
    released = []
    def release(row, comment, *, operator_stopped):
        assert row['id'] == world.row['id'] and operator_stopped and comment
        released.append(row['id'])
        world.row.update(assignee='', status='open', revision=2)
        return 'released'
    world.tracker.release_stranded = release
    monkeypatch.setattr(stranded_adapter, 'checkpoint', lambda _: dict(
        worktree='fixture:preserved', branch='fixture-branch', head='a' * 40,
        checkpoint='fixture:retained notes'))
    install(world, [record(binding='registry'), record('peer', kind='review-reservation')])
    FilesStops(world.root / 'stopped').record('worker', 0)
    run(world, 0)  # Start the item's measured interval under the shared policy.
    run(world, 1800)
    assert released == ['work-1'] and world.row['assignee'] == ''
    from shantytown.item_orphan_metrics import metrics as item_metrics
    assert 'shantytown_orphaned_work{kind="items"} 0' in item_metrics(world.root, now=1800)
    assert Duties(world.root).resolve('queue', live=lambda n: n == 'lead') == 'lead'
    assert len(world.repairs) == 1 and decision['assignee'] == 'worker'
    world.panes.exists = lambda _: False
    monkeypatch.setattr(cli, '_registry', lambda _: world.registry)
    monkeypatch.setattr(cli, '_panes', lambda _: world.panes)
    monkeypatch.setattr(cli, '_tracker', lambda _: world.tracker)
    monkeypatch.setattr(cli, '_inbox', lambda _: world.inbox)
    stopped = []
    monkeypatch.setattr(cli, '_stop_locked', lambda _: stopped.append('worker') or 0)
    args = SimpleNamespace(root=world.root, agent='worker', dry_run=False, repool_work=True)
    assert cli._cmd_stop(args) == 0
    assert stopped == ['worker'] and len(world.repairs) == 1
    assert decision['assignee'] == 'worker' and released == ['work-1']


def test_internal_landing_seeds_author_rule_and_checks_liveness_at_send_time(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    duties = Duties(world.root)
    plan = dict(schema=SCHEMA, revision=1, coverage=list(KINDS),
                routing=ROUTING_RULES, entries=[])
    duties.install(plan, expected_revision=0, apply=True)
    assert duties.load()['routing'] == ROUTING_RULES
    sent = duties.send_landing('internal/example', 'lead', 'reviewed landing task',
        'fixture:landing', live=lambda n: world.states[n] == 'live', inbox=world.inbox)
    assert sent.body == 'fixture:landing reviewed landing task' and len(world.inbox.unread('lead')) == 1
    world.states['lead'] = 'down'
    with pytest.raises(ValueError, match='stopped'):
        duties.send_landing('internal/example', 'lead', 'cached target', 'fixture:next',
            live=lambda n: world.states[n] == 'live', inbox=world.inbox)
    assert len(world.inbox.unread('lead')) == 1 and not world.inbox.unread('worker')
    changed = duties.load()
    changed['routing']['internal-landing']['holder_rule'] = 'queue'
    with pytest.raises(ValueError, match='live author'):
        duties.install(changed, expected_revision=1, apply=True)
    assert duties.load()['routing'] == ROUTING_RULES
    with pytest.raises(ValueError, match='repository'):
        duties.send_landing('public/example', 'lead', 'wrong lane', 'fixture:wrong',
            live=lambda _: True, inbox=world.inbox)


def test_shared_dry_run_previews_new_jobs_and_due_duties_without_any_write(setup, monkeypatch):
    from shantytown import duties as duty_module, duty_metrics
    world = armed(setup, monkeypatch)
    install(world, [record(binding='registry')])
    FilesStops(world.root / 'stopped').record('worker', 0)
    jobs = world.root / 'jobs'
    jobs.mkdir()
    (jobs / 'daily.toml').write_text('[trigger]\nevery="1h"\n[action]\ninbox="worker"\nmessage="work"\n')
    before = {str(p.relative_to(world.root)): p.read_bytes()
              for p in world.root.rglob('*') if p.is_file()}
    def forbidden(*_args, **_kwargs):
        pytest.fail('dry-run attempted an effect')
    monkeypatch.setattr(duty_module, 'write_json_atomic', forbidden)
    monkeypatch.setattr(duty_adapter, 'write_json_atomic', forbidden)
    monkeypatch.setattr(duty_metrics, 'publish', forbidden)
    world.tracker.create_duty_issue = forbidden
    result = sweep(world.root, world.registry, world.tracker, world.panes, world.inbox,
                   now=14400, dry_run=True)
    assert ('queue', 'orphaned duty (dry-run; no effects)') in result
    assert any(name.startswith('job:') and 'dry-run' in state for name, state in result)
    assert Duties(world.root).load()['entries'][0]['holder'] == 'worker'
    assert {str(p.relative_to(world.root)): p.read_bytes()
            for p in world.root.rglob('*') if p.is_file()} == before


def test_dry_run_without_installed_inventory_is_unknown_and_creates_nothing(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    assert not Duties(world.root).root.exists()
    result = sweep(world.root, world.registry, world.tracker, world.panes, world.inbox,
                   now=1800, dry_run=True)
    assert result == [] and 'UNKNOWN' in summary(world.root, now=1800)
    assert not Duties(world.root).root.exists() and not world.repairs


def test_nonfinite_retained_clock_cannot_trigger_early_repair(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record()])
    run(world, 0)
    path = Duties(world.root).root / 'attention.json'
    data = json.loads(path.read_text())
    data['queue']['since'] = float('nan')
    write_json_atomic(path, data)
    assert ('duties', 'duty census UNKNOWN') in run(world, 1)
    assert not world.repairs and 'UNKNOWN' in summary(world.root, now=1)


def test_parked_inferred_down_owner_is_flagged_but_never_released(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    world.row.update(title='parked ordinary work', labels=['parked:by-design'],
                     status='deferred', defer_until='2099-01-01T00:00:00Z')
    # No operator stop stamp: positive process absence admits attention only.
    run(world, 0)
    result = run(world, 1800)
    assert ('work-1', 'needs attention') in result
    assert world.row['assignee'] == 'worker' and world.row['status'] == 'deferred'
    assert len(world.inbox.unread('admin')) == 1
    from shantytown.item_orphan_metrics import metrics as item_metrics
    assert 'shantytown_orphaned_work{kind="items"} 1' in item_metrics(world.root, now=1800)


def test_item_metric_unknown_cannot_become_zero_or_freshen_a_stale_census(tmp_path):
    from shantytown.item_orphan_metrics import metrics as item_metrics
    path = tmp_path / 'stranded-work/orphans.json'
    path.parent.mkdir()
    write_json_atomic(path, dict(checked_at=0, complete=True, orphaned=0))
    text = item_metrics(tmp_path, now=901)
    assert 'item_census_complete 0' in text and 'shantytown_orphaned_work{' not in text
    assert 'timestamp_seconds 0' in text
    write_json_atomic(path, dict(checked_at=float('nan'), complete=True, orphaned=0))
    text = item_metrics(tmp_path, now=1)
    assert 'item_census_complete 0' in text and 'nan' not in text
    write_json_atomic(path, dict(checked_at=1, complete=False, orphaned=0))
    assert 'shantytown_orphaned_work{' not in item_metrics(tmp_path, now=1)


def test_failed_item_projection_stays_unknown_while_independent_duty_recovers(setup, monkeypatch):
    from shantytown.item_orphan_metrics import metrics as item_metrics
    world = armed(setup, monkeypatch)
    install(world, [record(binding='registry')])
    FilesStops(world.root / 'stopped').record('worker', 0)
    def unavailable(_owners):
        raise ValueError('projection incomplete')
    world.tracker.stranded_rows = unavailable
    with pytest.raises(ValueError, match='projection incomplete'):
        run(world, 1800)
    assert Duties(world.root).resolve('queue', live=lambda n: n == 'lead') == 'lead'
    text = item_metrics(world.root, now=1800)
    assert 'item_census_complete 0' in text and 'shantytown_orphaned_work{' not in text
    assert 'shantytown_orphaned_duties{kind="merge-queue"} 0' in metrics(world.root, now=1800)


def test_stopping_administrator_cannot_repair_to_the_same_stopping_holder(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    row = record()
    row['holder'] = 'admin'
    install(world, [row])
    args = SimpleNamespace(root=world.root, agent='admin', dry_run=False, repool_work=True)
    with pytest.raises(ValueError, match='administrator'):
        duty_adapter.stop_guard(args, lambda: pytest.fail('administrator stopped'),
            registry=world.registry, panes=world.panes, inbox=world.inbox,
            tracker=world.tracker, host='test-host')
    assert not world.repairs and not world.inbox.unread('admin')


def test_malformed_truthy_census_flag_cannot_certify_zero(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [])
    write_json_atomic(Duties(world.root).root / 'report.json', dict(
        checked_at=0, complete='false', orphaned={kind: 0 for kind in KINDS}))
    assert 'UNKNOWN' in summary(world.root, now=1)
    text = metrics(world.root, now=1)
    assert 'census_complete 0' in text and 'shantytown_orphaned_duties{' not in text


def test_positive_live_owner_is_untouched(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record(binding='registry')])
    world.states['worker'] = 'live'
    run(world, 100000)
    assert Duties(world.root).load()['entries'][0]['holder'] == 'worker'
    assert not world.repairs and not world.inbox.unread('admin')
    assert '0 orphaned' in summary(world.root, now=100000)


def test_measured_absence_uses_tier_threshold_and_live_resets_interval(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record('urgent'), record('ordinary', priority=2)])
    run(world, 0)
    run(world, 1799)
    assert not world.repairs
    run(world, 1800)
    assert len(world.repairs) == 1
    run(world, 14400)
    assert len(world.repairs) == 2
    world.states['worker'] = 'live'
    run(world, 15000)
    world.states['worker'] = 'down'
    run(world, 15001)
    assert '0 orphaned' in summary(world.root, now=15001)


def test_unknown_or_changed_card_never_reports_clean_or_reassigns(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record(binding='registry')])
    world.registry.get = lambda name: replace(world.cards[name], pane='changed-pane')
    result = run(world, 100000)
    assert ('queue', 'duty owner liveness UNKNOWN') in result
    assert 'UNKNOWN' in summary(world.root, now=100000)
    text = metrics(world.root, now=100000)
    assert 'census_complete 0' in text and 'shantytown_orphaned_duties{' not in text
    assert not world.repairs


def test_held_agent_is_not_a_live_handoff_candidate(setup, monkeypatch):
    from shantytown import agent_hold
    world = armed(setup, monkeypatch)
    install(world, [record(binding='registry')])
    agent_hold.hold(world.root, 'lead', 'admin', 'controlled hold')
    FilesStops(world.root / 'stopped').record('worker', 0)
    run(world, 1800)
    assert Duties(world.root).load()['entries'][0]['holder'] == 'worker'
    assert len(world.repairs) == 1


def test_author_cannot_receive_their_reserved_review(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    row = record(binding='registry', kind='review-reservation')
    row['authors'] = ['lead']
    install(world, [row])
    FilesStops(world.root / 'stopped').record('worker', 0)
    run(world, 1800)
    assert Duties(world.root).load()['entries'][0]['holder'] == 'worker'
    assert len(world.repairs) == 1


def test_lost_create_reply_reuses_native_identity_not_another_task(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record()])
    FilesStops(world.root / 'stopped').record('worker', 0)
    create = world.tracker.create_duty_issue

    def uncertain(*args, **kwargs):
        result = create(*args, **kwargs)
        if len(world.attempts) == 1:
            raise TimeoutError('committed, reply lost')
        return result

    world.tracker.create_duty_issue = uncertain
    run(world, 1800)
    run(world, 1900)
    assert len(world.attempts) == 2 and len(world.repairs) == 1
    assert world.attempts[0] == world.attempts[1]
    assert len(world.inbox.unread('admin')) == 1


def test_action_budget_rotates_past_already_reported_duties(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record('rule-' + str(i)) for i in range(25)])
    FilesStops(world.root / 'stopped').record('worker', 0)
    for at in [1800, 1900, 2000]:
        run(world, at)
    assert len(world.repairs) == 25
    assert len(world.inbox.unread('admin')) == 25


def test_missing_or_stale_coverage_is_unknown(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    run(world, 0)
    assert 'UNKNOWN' in summary(world.root, now=0)
    install(world, [record()])
    world.states['worker'] = 'live'
    run(world, 100)
    assert 'UNKNOWN' in summary(world.root, now=1001)
    assert 'census_complete 0' in metrics(world.root, now=1001)


def test_stop_refuses_before_kill_without_explicit_disposition(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record()])
    a = SimpleNamespace(root=world.root, agent='worker', dry_run=False, repool_work=False)
    with pytest.raises(ValueError, match='--repool-work'):
        duty_adapter.stop_guard(a, lambda: pytest.fail('pane stopped'),
            registry=world.registry, panes=world.panes, inbox=world.inbox,
            tracker=world.tracker, host='test-host')
    assert not world.repairs


def test_stop_explicit_repool_routes_external_duty_before_kill(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record()])
    a = SimpleNamespace(root=world.root, agent='worker', dry_run=False, repool_work=True)
    def stop():
        assert len(world.repairs) == 1
        assert len(world.inbox.unread('admin')) == 1
        assert world.row['assignee'] == 'worker'  # ASK still untouched.
        return 0
    assert duty_adapter.stop_guard(a, stop, registry=world.registry, panes=world.panes,
        inbox=world.inbox, tracker=world.tracker, host='test-host') == 0
    assert Duties(world.root).load()['entries'][0]['holder'] == 'worker'


def test_registry_conflict_and_external_handoff_refuse(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record()])
    with pytest.raises(ValueError, match='revision'):
        Duties(world.root).handoff('queue', 'lead', expected_revision=2, live=lambda _: True)
    with pytest.raises(ValueError, match='unsupported'):
        Duties(world.root).handoff('queue', 'lead', expected_revision=1, live=lambda _: True)
    data = Duties(world.root).load()
    data['entries'].append(data['entries'][0])
    write_json_atomic(Duties(world.root).path, data)
    with pytest.raises(ValueError, match='duplicate'):
        Duties(world.root).load()
    assert ('duties', 'duty census UNKNOWN') in run(world, 1800)


def test_inventory_refresh_preserves_supported_handoff_and_missing_records(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record(binding='registry'), record('retained')])
    duties = Duties(world.root)
    duties.handoff('queue', 'lead', expected_revision=1, live=lambda _: True)
    plan = dict(schema=SCHEMA, revision=1, coverage=list(KINDS),
                entries=[record(binding='registry')])
    before = duties.load()
    assert not duties.install(plan, expected_revision=before['revision'])['changed']
    duties.install(plan, expected_revision=before['revision'], apply=True)
    assert duties.load() == before
    assert duties.resolve('queue', live=lambda n: n == 'lead') == 'lead'
    with pytest.raises(ValueError, match='revision'):
        duties.install(plan, expected_revision=0, apply=True)


def test_after_turn_never_releases_a_still_running_writers_work(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record()])
    a = SimpleNamespace(root=world.root, agent='worker', dry_run=False,
                        repool_work=True, after_turn=True)
    with pytest.raises(ValueError, match='completed turn boundary'):
        duty_adapter.stop_guard(a, lambda: pytest.fail('pane stopped'),
            registry=world.registry, panes=world.panes, inbox=world.inbox,
            tracker=world.tracker, host='test-host')
    assert not world.repairs


def test_foreign_holder_stop_refuses_before_any_work_mutation(setup, monkeypatch):
    world = armed(setup, monkeypatch)
    install(world, [record()])
    world.cards['worker'] = replace(world.cards['worker'], host='other-host')
    a = SimpleNamespace(root=world.root, agent='worker', dry_run=False, repool_work=True)
    with pytest.raises(ValueError, match='not scoped'):
        duty_adapter.stop_guard(a, lambda: pytest.fail('pane stopped'),
            registry=world.registry, panes=world.panes, inbox=world.inbox,
            tracker=world.tracker, host='test-host')
    assert not world.repairs


def test_sdk_repair_uses_stable_workflow_identity_and_reads_exact_p0(monkeypatch):
    from subprocess import CompletedProcess
    import hashlib
    from shantytown.protocols import WorkItem
    from shantytown.sd import SdTracker
    tracker = object.__new__(SdTracker)
    payload = {k: record()[k] for k in ('id', 'kind', 'holder', 'source')}
    key = 'stranded-duty:' + hashlib.sha256(payload['id'].encode()).hexdigest()
    calls = []
    def command(*args):
        calls.append(args)
        return CompletedProcess(args, 0, '{"id":"fixture-1"}', '')
    monkeypatch.setattr(tracker, '_bd', command)
    monkeypatch.setattr(tracker, 'get', lambda _: WorkItem(id='fixture-1',
        title='P0 orphaned duty: queue', status='open', priority=0,
        assignee='admin', description=key + '\n' + json.dumps(payload)))
    assert tracker.create_duty_issue(payload, target='admin', key=key).id == 'fixture-1'
    assert tracker.create_duty_issue(payload, target='admin', key=key).id == 'fixture-1'
    assert calls[0] == calls[1]
    assert '--visit=1' in calls[0] and '--step=repair' in calls[0]
    assert any(s.startswith('--workflow-run=urn:shantytown:duty:') for s in calls[0])
    assert '--priority=0' in calls[0] and '--labels=orphaned-duty' in calls[0]
    with pytest.raises(ValueError, match='identity'):
        tracker.create_duty_issue(payload, target='admin', key='different')
    assert len(calls) == 2


def test_metric_publisher_has_no_ambient_or_secret_diagnostic(monkeypatch, tmp_path):
    from shantytown import duty_metrics
    monkeypatch.setattr(duty_metrics, '_push', lambda *_: pytest.fail('unconfigured network'))
    assert duty_metrics.publish(tmp_path) is False
    monkeypatch.setenv('ST_GOVERNOR_PUSHGATEWAY', 'https://gateway.example')
    monkeypatch.setattr(duty_metrics, 'physical_hostname', lambda: 'fixture-host')
    monkeypatch.setattr(duty_metrics, 'metrics', lambda *_a, **_k: 'census 0\n')
    calls = []
    monkeypatch.setattr(duty_metrics, '_push', lambda *a: calls.append(a))
    assert duty_metrics.publish(tmp_path, now=1) is True
    assert calls == [('https://gateway.example', 'st_duties', 'fixture-host',
                     'census 0\nshantytown_item_census_complete 0\n'
                     'shantytown_item_census_timestamp_seconds 1\n')]
