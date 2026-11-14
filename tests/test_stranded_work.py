"""Offline real policy/outbox/CAS controls; no fleet process or board access."""
from contextlib import nullcontext
import copy
import json
from types import SimpleNamespace

import pytest

from shantytown.owned_work import OwnedWork
from shantytown.stranded_work import StrandedWork, T1, T2, eligible


@pytest.fixture
def world(tmp_path):
    service = StrandedWork(tmp_path)
    row = dict(id='work-1', assignee='worker', status='open', priority=1,
               title='work', labels=[], revision=7, notes='checkpoint must survive')
    observation = dict(state='down', generation='first', resume_at=None)
    notices, writes = [], []
    def release(current, comment):
        writes.append((copy.deepcopy(current), json.loads(comment)))
        if current['revision'] != row['revision']:
            return 'conflict'
        row.update(assignee='', status='open', revision=row['revision'] + 1)
        return 'released'
    args = dict(observe=lambda *_: dict(observation),
                recipient=lambda *_: 'lead',
                notify=lambda *args: notices.append(args),
                read=lambda _: copy.deepcopy(row), release=release,
                checkpoint=lambda *_: dict(worktree='/work/retained', branch='feature/held',
                                            checkpoint='work-1 original comment'),
                fence=lambda _: nullcontext(), release_admitted=True)
    def tick(at, **overrides):
        return service.tick([copy.deepcopy(row)], {'worker': object()}, now=at,
                            **(args | overrides))
    return SimpleNamespace(service=service, row=row, observation=observation,
                           notices=notices, writes=writes, args=args, tick=tick)


def test_old_lifecycle_service_does_not_discover_unrecorded_owner(tmp_path):
    def forbidden(*args):
        pytest.fail('old service unexpectedly discovered an owner without state')
    assert OwnedWork(tmp_path).tick(None, forbidden, None, now=0) == []


def test_one_hour_open_release_preserves_checkpoint(world):
    assert world.tick(0) == []
    assert world.tick(T1) == []
    world.tick(T1 + 1)
    assert len(world.notices) == len(world.writes) == 1
    before, comment = world.writes[0]
    assert before['revision'] == 7
    assert comment['original_owner'] == 'worker' and comment['down_since'] == 0
    assert comment['worktree'] == '/work/retained' and comment['branch'] == 'feature/held'
    assert comment['checkpoint'] == 'work-1 original comment'
    assert world.row['assignee'] == '' and world.row['status'] == 'open'
    assert world.row['notes'] == 'checkpoint must survive'
    world.tick(T1 + 2)
    assert len(world.writes) == 1


@pytest.mark.parametrize('priority', range(5))
@pytest.mark.parametrize('status', ['open', 'in_progress'])
def test_uniform_threshold_open_only_and_persistent_attention(world, priority, status):
    world.row.update(priority=priority, status=status)
    world.tick(0)
    world.tick(T1)
    assert not world.notices and not world.writes
    world.tick(T1 + 1)
    assert len(world.notices) == 1
    assert len(world.writes) == (status == 'open')
    if status == 'in_progress':
        world.tick(T1 + 2)
        assert len(world.notices) == 1
        assert world.row['assignee'] == 'worker'
        assert world.service.snapshot()['work-1']['attention']


def test_observation_mode_never_releases(world):
    world.tick(0, release_admitted=False)
    world.tick(T1 + 1, release_admitted=False)
    assert len(world.notices) == 1 and not world.writes


@pytest.mark.parametrize('change', [dict(defer_until='1970-01-01T00:00:01Z'),
    dict(status='deferred'), dict(labels=['blocked:human']), dict(blocker_kind='external'),
    dict(labels=['needs-stiwi']), dict(title='ASK operator: keep parked'),
    dict(labels='malformed'), dict(priority=None), dict(title='inbox: message')])
def test_parked_and_unproven_items_never_observed_or_mutated(world, change):
    world.row.update(change)
    world.tick(T2)
    assert world.notices == world.writes == []


@pytest.mark.parametrize('state', ['live', 'unknown'])
def test_live_or_unknown_owner_never_alerted_or_released(world, state):
    world.row['priority'] = 0
    world.observation['state'] = state
    world.tick(0)
    world.tick(T2)
    assert world.notices == world.writes == []


def test_unknown_gap_and_restart_reset_down_clock(world):
    world.tick(0)
    world.observation['state'] = 'unknown'
    world.tick(T2)
    world.observation['state'] = 'down'
    world.tick(T2 + 1)
    assert world.writes == [] and world.notices == []
    world.observation['generation'] = 'new-launch'
    world.tick(T2 * 2)
    assert world.writes == []


@pytest.mark.parametrize('resume', ['2999-01-01T00:00:00Z', 'invalid', '2027-01-01'])
def test_intentional_resume_or_unknown_intent_exempt(world, resume):
    world.row['priority'] = 0
    world.observation['resume_at'] = resume
    world.tick(0)
    assert world.notices == world.writes == []


def test_missing_card_has_same_measured_hour(world):
    world.observation['state'] = 'missing'
    world.tick(0)
    assert not world.notices and not world.writes
    world.tick(T2 + 1)
    assert len(world.notices) == len(world.writes) == 1


def test_live_race_after_checkpoint_prevents_release(world):
    world.row['priority'] = 0
    def checkpoint(*args):
        world.observation['state'] = 'live'
        return dict(worktree='preserved', branch='kept', checkpoint='kept')
    world.tick(0)
    world.tick(T1 + 1, checkpoint=checkpoint)
    assert not world.writes


def test_owner_parking_race_prevents_release(world):
    world.row['priority'] = 0
    def read(_):
        world.row['labels'] = ['blocked:human']
        return dict(world.row)
    world.tick(0)
    world.tick(T1 + 1, read=read)
    assert not world.writes


def test_unknown_checkpoint_keeps_ownership(world):
    world.row['priority'] = 0
    world.tick(0)
    world.tick(T1 + 1, checkpoint=lambda *_: None)
    assert not world.writes and world.row['assignee'] == 'worker'


@pytest.mark.parametrize('boundary', ['release', 'notify'])
def test_indeterminate_release_and_delivery_are_not_retried(world, boundary):
    world.row['priority'] = 0
    attempted = []
    def unknown(*args):
        attempted.append(args)
        raise TimeoutError('possibly committed')
    world.tick(0)
    world.tick(T1 + 1, **{boundary: unknown})
    world.tick(T1 + 2, **{boundary: unknown})
    assert len(attempted) == 1
    state = world.service.snapshot()['work-1']
    assert state['release' if boundary == 'release' else 'notice'] == 'unknown'
    if boundary == 'notify':
        assert not world.writes


def test_checked_live_clears_only_process_observation_not_operator_intent(tmp_path):
    service = OwnedWork(tmp_path)
    service.confirmed_down('worker', now=10)
    assert service.snapshot()['worker']['process_observation']
    service.confirmed_live('worker', now=20)
    assert service.snapshot()['worker']['state'] == 'live'
    service.stop('worker', at=30, reason='operator')
    service.confirmed_down('worker', now=40)
    service.confirmed_live('worker', now=50)
    assert service.snapshot()['worker']['state'] == 'stopped'
    assert service.snapshot()['worker']['reason'] == 'operator'


def test_default_adapter_does_not_touch_backend_or_panes(tmp_path):
    from shantytown.stranded_adapter import sweep
    assert sweep(tmp_path, None, None, None, None) == []


def test_partial_card_census_refuses_without_observations(tmp_path, monkeypatch):
    from shantytown.answer import Answer, PartialAnswer
    from shantytown.stranded_adapter import sweep
    monkeypatch.setenv('SHANTY_STRANDED_WORK', 'observe')
    monkeypatch.setattr('shantytown.deployment.local_host', lambda _: 'test-host')
    registry = SimpleNamespace(all=lambda: Answer.capped([], how='fixture', caveat='partial'))
    with pytest.raises(PartialAnswer):
        sweep(tmp_path, registry, None, None, None)


@pytest.mark.parametrize('rc,stdout,expected', [(1, '', 'unknown'),
    (0, '%1\tother\tcodex\n', 'down'), (0, '%1\tworker\tbash\n', 'down'),
    (0, '%1\tworker\tcodex\n', 'live'), (0, 'malformed\n', 'unknown'),
    (0, '%1\tworker\tpython\n', 'unknown')])
def test_tmux_checked_failure_is_not_absence(monkeypatch, rc, stdout, expected):
    from shantytown.tmux import Tmux
    monkeypatch.setattr('shantytown.tmux.subprocess.run',
        lambda *a, **kw: SimpleNamespace(returncode=rc, stdout=stdout))
    assert Tmux().owner_state('worker') == expected


def test_sdk_release_has_revision_and_atomic_comment_and_exact_readback(monkeypatch):
    from shantytown.sd import SdTracker
    tracker = SdTracker(store='/synthetic/store', prefix='work')
    row = dict(id='work-1', status='open', assignee='worker', priority=1,
               title='work', labels=[], revision=7)
    calls = []
    def sdk(identity, *args):
        calls.append(args)
        if args[0] == 'update':
            return SimpleNamespace(returncode=0, stdout='{}')
        return SimpleNamespace(returncode=0, stdout=json.dumps([
            row | dict(status='open', assignee='', revision=8, comments=[dict(text='audit')])]))
    monkeypatch.setattr(tracker, '_bd_for', sdk)
    assert tracker.release_stranded(row, 'audit') == 'released'
    assert '--if-revision=7' in calls[0] and '--transition-comment=audit' in calls[0]
    assert '--assignee=' in calls[0] and not any(x.startswith('--status') for x in calls[0])
    assert calls[1] == ('show', 'work-1', '--json')


@pytest.mark.parametrize('rc,expected', [(4, 'conflict'), (1, None)])
def test_sdk_conflict_or_failure_never_falls_back_to_generic_update(monkeypatch, rc, expected):
    from shantytown.sd import SdTracker
    tracker = SdTracker(store='/synthetic/store', prefix='work')
    calls = []
    def sdk(*args):
        calls.append(args)
        return SimpleNamespace(returncode=rc, stdout='')
    monkeypatch.setattr(tracker, '_bd_for', sdk)
    row = dict(id='work-1', status='open', assignee='worker', priority=0, title='work', revision=7)
    if expected:
        assert tracker.release_stranded(row, 'audit') == expected
    else:
        with pytest.raises(RuntimeError, match='UNKNOWN'):
            tracker.release_stranded(row, 'audit')
    assert len(calls) == 1


@pytest.mark.parametrize('status', ['open', 'hooked', 'in_progress', 'blocked', 'deferred'])
def test_operator_release_preserves_parked_status_and_all_fields(world, status, monkeypatch):
    world.row.update(status=status, title='parked work', labels=['blocked:external'],
                     defer_until='2999-01-01T00:00:00Z', notes='resume_when: gate')
    world.observation.update(state='operator-stopped', intentional_stop=True)
    writes = []
    def release(current, comment, *, operator_stopped=False):
        assert operator_stopped is True
        writes.append(copy.deepcopy(current))
        world.row.update(assignee='', revision=world.row['revision'] + 1)
        return 'released'
    before = copy.deepcopy(world.row)
    world.tick(10, operator_release_only=True, release=release)
    assert len(writes) == 1
    assert world.row == before | dict(assignee='', revision=before['revision'] + 1)


def _operator_release(world):
    """A release fake that accepts the operator path's keyword (the shared
    world fake does not, so operator-path assertions there pass vacuously)."""
    def release(current, comment, *, operator_stopped=False):
        assert operator_stopped is True
        world.writes.append((copy.deepcopy(current), json.loads(comment)))
        world.row.update(assignee='', revision=world.row['revision'] + 1)
        return 'released'
    return release


def test_operator_release_fake_positive_control(world):
    """Control for the exclusion tests below: an ordinary item IS released."""
    world.row.update(status='open', title='work', labels=[])
    world.observation.update(state='operator-stopped', intentional_stop=True)
    world.tick(10, operator_release_only=True, release=_operator_release(world))
    assert len(world.writes) == 1 and world.row['assignee'] == ''


@pytest.mark.parametrize('ask', [dict(title='ASK Stiwi: decide'), dict(title='ASK operator: retained'),
    dict(labels=['desk']), dict(labels=['needs-stiwi']), dict(labels=['decision-needed']),
    dict(labels=['blocked:human']), dict(blocker_kind='blocked:human')])
def test_operator_release_never_takes_ask_or_desk_class_items(world, ask):
    """A decision held for a person is not capacity; it stays with its owner."""
    world.row.update(status='open', **ask)
    world.observation.update(state='operator-stopped', intentional_stop=True)
    world.tick(10, operator_release_only=True, release=_operator_release(world))
    assert not world.writes
    assert world.row['assignee'] == 'worker'


def test_operator_release_rechecks_stop_under_lifecycle_fence(world):
    world.observation.update(state='operator-stopped', intentional_stop=True)
    def checkpoint(*_):
        world.observation['state'] = 'live'
        return dict(worktree='kept', branch='kept', checkpoint='kept')
    world.tick(10, operator_release_only=True, checkpoint=checkpoint)
    assert not world.writes


@pytest.mark.parametrize('status', ['open', 'blocked', 'deferred'])
def test_operator_sdk_cas_changes_only_assignee_with_exact_readback(monkeypatch, status):
    from shantytown.sd import SdTracker
    tracker = SdTracker(store='/synthetic/store', prefix='work')
    row = dict(id='work-1', status=status, assignee='worker', priority=1,
               title='parked work', labels=['blocked:external'], revision=7,
               notes='resume_when: gate', defer_until='2999-01-01T00:00:00Z')
    calls = []
    def sdk(identity, *args):
        calls.append(args)
        if args[0] == 'update':
            return SimpleNamespace(returncode=0, stdout='{}')
        return SimpleNamespace(returncode=0, stdout=json.dumps([
            row | dict(assignee='', revision=8, comments=[dict(text='audit')])]))
    monkeypatch.setattr(tracker, '_bd_for', sdk)
    assert tracker.release_stranded(row, 'audit', operator_stopped=True) == 'released'
    assert calls[0] == ('update', 'work-1', '--assignee=', '--if-revision=7',
                        '--transition-comment=audit', '--json')


def test_operator_sdk_returns_in_progress_work_to_open_in_the_same_cas(monkeypatch):
    """An unassigned in_progress item is on no plate and outside ready work."""
    from shantytown.sd import SdTracker
    tracker = SdTracker(store='/synthetic/store', prefix='work')
    row = dict(id='work-1', status='in_progress', assignee='worker', priority=0,
               title='work', labels=[], revision=7, notes='checkpoint')
    calls = []
    def sdk(identity, *args):
        calls.append(args)
        if args[0] == 'update':
            return SimpleNamespace(returncode=0, stdout='{}')
        return SimpleNamespace(returncode=0, stdout=json.dumps([
            row | dict(assignee='', status='open', revision=8, comments=[dict(text='audit')])]))
    monkeypatch.setattr(tracker, '_bd_for', sdk)
    assert tracker.release_stranded(row, 'audit', operator_stopped=True) == 'released'
    assert calls[0] == ('update', 'work-1', '--assignee=', '--status=open',
                        '--if-revision=7', '--transition-comment=audit', '--json')


def test_operator_sdk_in_progress_readback_must_show_open(monkeypatch):
    from shantytown.sd import SdTracker
    tracker = SdTracker(store='/synthetic/store', prefix='work')
    row = dict(id='work-1', status='in_progress', assignee='worker', priority=0,
               title='work', labels=[], revision=7)
    def sdk(identity, *args):
        if args[0] == 'update':
            return SimpleNamespace(returncode=0, stdout='{}')
        return SimpleNamespace(returncode=0, stdout=json.dumps([
            row | dict(assignee='', revision=8, comments=[dict(text='audit')])]))
    monkeypatch.setattr(tracker, '_bd_for', sdk)
    with pytest.raises(RuntimeError, match='UNKNOWN'):
        tracker.release_stranded(row, 'audit', operator_stopped=True)


def test_operator_sdk_refuses_to_claim_release_when_parking_changed(monkeypatch):
    from shantytown.sd import SdTracker
    tracker = SdTracker(store='/synthetic/store', prefix='work')
    row = dict(id='work-1', status='deferred', assignee='worker', priority=1,
               title='work', labels=[], revision=7, notes='retain')
    def sdk(identity, *args):
        result = [] if args[0] == 'update' else [row | dict(
            assignee='', status='open', revision=8, comments=[dict(text='audit')])]
        return SimpleNamespace(returncode=0, stdout=json.dumps(result))
    monkeypatch.setattr(tracker, '_bd_for', sdk)
    with pytest.raises(RuntimeError, match='UNKNOWN'):
        tracker.release_stranded(row, 'audit', operator_stopped=True)


def test_stranded_sdk_census_uses_owned_waiting_work_projection_without_messages(monkeypatch):
    from shantytown.sd import SdTracker
    tracker = SdTracker(store='/synthetic/store', prefix='work')
    monkeypatch.setattr(tracker, '_use_remote_projection', lambda: True)
    monkeypatch.setattr(tracker, 'prove_store', lambda: 'proof')
    calls = []
    def read(proof, owner, **options):
        from shantytown.answer import Answer
        calls.append((proof, owner, options))
        return Answer.complete_read([dict(id='work-1')], how='complete fixture')
    monkeypatch.setattr('shantytown.seeds_plate.owner_rows', read)
    assert tracker.stranded_rows(['worker']) == [dict(id='work-1')]
    assert calls == [('proof', None, dict(timeout=tracker.timeout,
        plate_owners=('worker',), capacity=True, include_deferred=True, include_messages=False, recovery_tokens=8))]


def test_attention_not_cleared_by_unreadable_metadata(world):
    world.row['priority'] = 0
    world.tick(0)
    world.tick(T1 + 1, release_admitted=False)
    world.row['priority'] = None
    world.tick(T1 + 2)
    state = world.service.snapshot()['work-1']
    assert state['active'] and state['attention'] and state['evidence'] == 'UNKNOWN'


def test_remote_intents_are_bounded_and_attention_retained(world):
    rows = [dict(world.row, id=f'work-{i}', priority=0) for i in range(8)]
    world.service.tick(rows, {}, now=0, **(world.args | dict(release_admitted=False)))
    assert not world.notices
    world.service.tick(rows, {}, now=T1 + 1, **(world.args | dict(release_admitted=False)))
    assert len(world.notices) == 4
    assert sum(entry['attention'] for entry in world.service.snapshot().values()) == 8
    world.service.tick(rows, {}, now=T1 + 2, **(world.args | dict(release_admitted=False)))
    assert len(world.notices) == 8


def test_elapsed_budget_keeps_unmeasured_evidence_untouched(world):
    stamps = iter([0, 6])
    result = world.tick(0, clock=lambda: next(stamps))
    assert 'budget exhausted' in result[0][1]
    assert not world.notices and not world.writes


def test_unknown_release_remains_a_launch_hold_across_unknown_observation(world):
    world.row['priority'] = 0
    attempts = []
    def unknown(*args):
        attempts.append(args)
        raise TimeoutError('possibly committed')
    world.tick(0)
    world.tick(T1 + 1, release=unknown)
    assert world.service.unresolved_release('worker')
    world.observation['state'] = 'unknown'
    world.tick(T1 + 2)
    world.observation['state'] = 'down'
    world.tick(T1 + 3, release=unknown)
    assert world.service.unresolved_release('worker')
    assert len(attempts) == 1


def test_adapter_refuses_in_progress_even_when_called_directly(monkeypatch):
    from shantytown.sd import SdTracker
    tracker = SdTracker(store='/synthetic/store', prefix='work')
    monkeypatch.setattr(tracker, '_bd_for', lambda *a: pytest.fail('must not write'))
    with pytest.raises(ValueError, match='eligible revision-bound'):
        tracker.release_stranded(dict(id='work-1', status='in_progress', assignee='worker',
            priority=0, title='work', labels=[], revision=7), 'audit')


def test_open_to_in_progress_race_never_releases(world):
    world.tick(0)
    def read(_):
        world.row['status'] = 'in_progress'
        return dict(world.row)
    world.tick(T1 + 1, read=read)
    assert not world.writes
    assert world.row['assignee'] == 'worker'


def _real_sd_read_shape(row, **changes):
    """The SDK full read: governed fields plus derived counters."""
    full = dict(row, comments_total=46, comments_folded=0, dependency_count=14,
                dependents=[dict(id='other', status='open', priority=1)],
                comments=[dict(text='older')], updated_at='2026-11-11T20:00:00Z')
    full.update(changes)
    return full


@pytest.mark.parametrize('status', ['deferred', 'in_progress', 'open', 'blocked'])
def test_release_readback_ignores_derived_counters_the_release_itself_bumps(monkeypatch, status):
    """aegis-byt live defect: comments_total 46 -> 47 made every release UNKNOWN."""
    from shantytown.sd import SdTracker
    tracker = SdTracker(store='/synthetic/store', prefix='work')
    row = _real_sd_read_shape(dict(id='work-1', status=status, assignee='worker', priority=0,
        title='work', labels=['blocked:external'], revision=40,
        defer_until='2026-11-12T14:00:00Z' if status == 'deferred' else None))
    def sdk(identity, *args):
        if args[0] == 'update':
            return SimpleNamespace(returncode=0, stdout='{}')
        after = _real_sd_read_shape(row, assignee=None, revision=41, comments_total=47,
            dependents=[dict(id='other', status='closed', priority=1)],
            updated_at='2026-11-11T20:03:02Z',
            comments=[dict(text='older'), dict(text='audit')],
            status='open' if status == 'in_progress' else status)
        return SimpleNamespace(returncode=0, stdout=json.dumps([after]))
    monkeypatch.setattr(tracker, '_bd_for', sdk)
    assert tracker.release_stranded(row, 'audit', operator_stopped=True) == 'released'


def test_release_readback_still_refuses_a_changed_governed_field(monkeypatch):
    from shantytown.sd import SdTracker
    tracker = SdTracker(store='/synthetic/store', prefix='work')
    row = _real_sd_read_shape(dict(id='work-1', status='deferred', assignee='worker',
        priority=0, title='work', labels=[], revision=40, defer_until='2026-11-12T14:00:00Z'))
    def sdk(identity, *args):
        if args[0] == 'update':
            return SimpleNamespace(returncode=0, stdout='{}')
        return SimpleNamespace(returncode=0, stdout=json.dumps([_real_sd_read_shape(
            row, assignee=None, revision=41, defer_until=None,
            comments=[dict(text='audit')])]))
    monkeypatch.setattr(tracker, '_bd_for', sdk)
    with pytest.raises(RuntimeError, match='UNKNOWN'):
        tracker.release_stranded(row, 'audit', operator_stopped=True)


@pytest.mark.parametrize('title', ['DESK: publish v0.17 - needs GO', 'desk - decide', 'ASK Stiwi: x'])
def test_operator_release_never_takes_desk_titled_items(world, title):
    world.row.update(status='open', title=title, labels=[])
    world.observation.update(state='operator-stopped', intentional_stop=True)
    world.tick(10, operator_release_only=True, release=_operator_release(world))
    assert not world.writes and world.row['assignee'] == 'worker'


def test_unknown_release_reconciles_only_on_exact_marker_comment(tmp_path):
    from shantytown.stranded_work import StrandedWork
    service = StrandedWork(tmp_path)
    service.root.mkdir(parents=True)
    journal = {
        'stranded-owner:a': dict(owner='w', item='done-1', outcome='unknown', comment='C1'),
        'stranded-owner:b': dict(owner='w', item='still-1', outcome='unknown', comment='C2'),
        'stranded-owner:c': dict(owner='v', item='nocomment-1', outcome='unknown', comment='C3'),
        'stranded-owner:d': dict(owner='u', item='claimed-1', outcome='unknown', comment='C4'),
    }
    (service.root / 'release-intents.json').write_text(json.dumps(journal))
    items = {'done-1': dict(assignee=None, comments=[dict(text='C1')]),
             'still-1': dict(assignee='w', comments=[dict(text='C2')]),
             'nocomment-1': dict(assignee=None, comments=[dict(text='other')]),
             # released, then claimed from the pool by a live agent before this tick
             'claimed-1': dict(assignee='live-agent', comments=[dict(text='C4')])}
    data = {}
    settled = service._reconcile(data, lambda i: items[i], now=5)
    assert sorted(settled) == [('claimed-1', 'release reconciled: released'),
                               ('done-1', 'release reconciled: released')]
    after = json.loads((service.root / 'release-intents.json').read_text())
    assert after['stranded-owner:a']['outcome'] == 'released'
    assert after['stranded-owner:b']['outcome'] == 'unknown'
    assert after['stranded-owner:c']['outcome'] == 'unknown'
    assert after['stranded-owner:d']['outcome'] == 'released'
    assert not service.unresolved_release('u')  # a pool claim must never fence the owner
    assert not service.unresolved_release('x') and service.unresolved_release('w')


@pytest.mark.parametrize('phase', ['planned', 'inflight', 'drained'])
@pytest.mark.parametrize('operator_stopped', [False, True])
@pytest.mark.parametrize('representation', ['label', 'context', 'json', 'malformed'])
def test_deploy_reservations_never_release(world, phase, operator_stopped, representation):
    context = {'deploy_admission': {'phase': phase, 'owner': 'worker'}}
    if representation == 'label':
        world.row['labels'] = ['deploy-operation']
    else:
        world.row['agent_context'] = (context if representation == 'context' else
                                     json.dumps(context) if representation == 'json' else '{broken')
    if operator_stopped:
        world.observation['state'] = 'operator-stopped'
    assert not eligible(world.row, operator_stopped=operator_stopped)
    world.tick(0, operator_release_only=operator_stopped)
    world.tick(T2 + 1, operator_release_only=operator_stopped)
    assert world.notices == world.writes == []
    assert world.row['assignee'] == 'worker' and world.row['revision'] == 7


def test_deploy_label_added_after_census_is_fenced(world):
    world.tick(0)
    def read(_):
        return dict(world.row, labels=['deploy-operation'])
    world.tick(T2 + 1, read=read)
    assert not world.writes
    assert world.row['assignee'] == 'worker'


def test_native_adapter_refuses_direct_deploy_release():
    from shantytown.sd import SdTracker
    class NoIO:
        def _bd_for(self, *args):
            pytest.fail('deploy release reached tracker write')
    row = dict(id='op-1', status='open', title='operation', assignee='worker',
               priority=0, labels=['deploy-operation'], revision=3)
    with pytest.raises(ValueError, match='eligible revision-bound'):
        SdTracker.release_stranded(NoIO(), row, 'preserve', operator_stopped=True)
