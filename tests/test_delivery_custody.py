"""Replay a lost Enter, queued preview, and foreign draft through real seams."""
import json
from types import SimpleNamespace

import pytest

from shantytown import delivery, tmux
from shantytown.events import FilesEvents
from shantytown.inbox import FilesInbox, Message
from test_codex_submission import transport, keys, READY, OWNED, BUSY, QUEUED, BODY


def local(monkeypatch, tmp_path, frames):
    panes, calls = transport(monkeypatch, frames)
    panes.delivery_root = tmp_path
    monkeypatch.setattr(panes, 'session_created', lambda _: 17.0)
    return panes, calls


def records(root):
    return [json.loads(p.read_text()) for p in (root / 'delivery').glob('send-*.json')]


def test_lost_enter_is_retried_once_then_only_owned_text_is_cleared(monkeypatch, tmp_path):
    panes, calls = local(monkeypatch, tmp_path, [READY, OWNED])
    original = panes.capture
    monkeypatch.setattr(panes, 'capture', lambda *a, **kw:
                        READY if any(c[-1] == 'C-u' for c in keys(calls)) else original(*a, **kw))
    with pytest.raises(tmux.PaneSubmissionUnverified):
        panes.send('worker', BODY)
    assert [c[-1] for c in keys(calls)] == [BODY, 'Enter', 'Enter', 'C-e', 'C-u']
    [record] = records(tmp_path)
    assert record['state'] == 'cleared'
    assert record['text'] == BODY
    assert (tmp_path / 'delivery').stat().st_mode & 0o777 == 0o700
    assert next((tmp_path / 'delivery').glob('send-*.json')).stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('foreign', [OWNED.replace(BODY, 'Human draft'), READY, 'unreadable'])
def test_foreign_or_unknown_composer_is_never_cleared(monkeypatch, tmp_path, foreign):
    panes, calls = local(monkeypatch, tmp_path, [READY, OWNED, OWNED, OWNED,
                                               OWNED, foreign])
    with pytest.raises(tmux.PaneSubmissionUnverified):
        panes.send('worker', BODY)
    assert not any(c[-1] in ('C-e', 'C-u') for c in keys(calls))


def test_human_draft_before_send_has_no_custody_or_keys(monkeypatch, tmp_path):
    panes, calls = local(monkeypatch, tmp_path, [OWNED.replace(BODY, 'Human draft')])
    with pytest.raises(tmux.PaneSubmissionUnverified):
        panes.send('worker', BODY)
    assert keys(calls) == []
    assert records(tmp_path) == []


def test_queue_is_unconfirmed_and_cannot_close_durable_pointer(monkeypatch, tmp_path, capsys):
    from shantytown import cli
    panes, calls = local(monkeypatch, tmp_path, [BUSY, QUEUED])
    box = FilesInbox(tmp_path / 'inbox')
    monkeypatch.setattr(cli, '_inbox', lambda *a, **kw: box)
    monkeypatch.setattr(panes, 'exists', lambda _: True)
    args = SimpleNamespace(root=tmp_path, agent='worker', backend='files', dry_run=False)
    card = SimpleNamespace(name='worker', pane='worker', host=None)
    assert cli._inbox_durable(args, card, BODY, panes) == cli.OK
    assert len(box.unread('worker')) == 1
    assert 'UNVERIFIED' in capsys.readouterr().out
    assert records(tmp_path)[0]['state'] == 'queued'
    assert not any(c[-1] in ('C-e', 'C-u') for c in keys(calls))


def test_no_persistence_means_no_typing(monkeypatch, tmp_path):
    panes, calls = local(monkeypatch, tmp_path, [READY])
    monkeypatch.setattr(delivery.Custody, 'save', lambda *_: (_ for _ in ()).throw(OSError('full')))
    with pytest.raises(tmux.PaneSubmissionUnverified, match='check delivery and custody before retrying'):
        panes.send('worker', BODY)
    assert keys(calls) == []


@pytest.mark.parametrize('session', [None, 99.0])
def test_unknown_or_changed_session_never_authorizes_clear(monkeypatch, tmp_path, session):
    panes, calls = local(monkeypatch, tmp_path, [READY, OWNED])
    births = iter([17.0, session, session])
    monkeypatch.setattr(panes, 'session_created', lambda _: next(births, session))
    with pytest.raises(tmux.PaneSubmissionUnverified):
        panes.send('worker', BODY)
    assert not any(c[-1] in ('C-e', 'C-u') for c in keys(calls))


def test_multiline_owned_notice_is_retained_without_clear(monkeypatch, tmp_path):
    body = BODY + '\nSecond line'
    panes, calls = local(monkeypatch, tmp_path, [READY, OWNED.replace(BODY, body)])
    with pytest.raises(tmux.PaneSubmissionUnverified):
        panes.send('worker', body)
    assert not any(c[-1] in ('C-e', 'C-u') for c in keys(calls))
    assert records(tmp_path)[0]['text'] == body


def fixtures(tmp_path, monkeypatch, *, state='queued', messages=None):
    from shantytown.files import FilesRegistry
    from shantytown.protocols import Agent
    panes, calls = local(monkeypatch, tmp_path, [READY])
    monkeypatch.setattr(panes, 'exists', lambda _: False)
    card = Agent('worker', pane='worker', reports_to='lead', harness='codex')
    reg = FilesRegistry(tmp_path / 'crew')
    reg.set(card)
    reg.set(Agent('lead', role='lead', pane='lead', reports_to='admin'))
    reg.set(Agent('admin', role='administrator', pane='admin'))
    box = FilesInbox(tmp_path / 'inbox')
    for text in messages or []:
        box.deliver('worker', text)
    if state:
        with delivery.Custody(tmp_path, 'worker') as c:
            c.begin(BODY, 17.0)
            c.finish(state)
    return panes, calls, card, reg, box


def observe(root, fixtures, screen, now):
    panes, _, card, reg, box = fixtures
    return delivery.supervise(root, reg, card, panes, box, screen, now=now)


def test_queue_retains_one_pointer_and_escalates_once_via_normal_event_drain(tmp_path, monkeypatch):
    from shantytown.stop_event import _compose_governance
    f = fixtures(tmp_path, monkeypatch)
    observe(tmp_path, f, QUEUED, 1000)
    assert len(f[-1].unread('worker')) == 1
    observe(tmp_path, f, QUEUED, 1299)
    events = FilesEvents(tmp_path / 'events')
    assert events.pending('lead') == []
    observe(tmp_path, f, QUEUED, 1300)
    observe(tmp_path, f, QUEUED, 1600)
    [event] = events.drain('lead')
    assert event.reason == 'delivery-stalled'
    assert 'busy=True' in event.detail
    assert 'box=' in event.detail
    assert 'WORKING UNTRACKED' not in _compose_governance([event], 1600)
    assert 'Unconfirmed message delivery' in _compose_governance([event], 1600)
    assert events.drain('lead') == []
    observe(tmp_path, f, QUEUED, 1900)
    assert events.pending('lead') == []
    assert len(f[-1].unread('worker')) == 1
    assert keys(f[1]) == []


def test_idle_legacy_inbox_alerts_without_touching_human_draft(tmp_path, monkeypatch):
    f = fixtures(tmp_path, monkeypatch, state=None, messages=['old message'])
    screen = OWNED.replace(BODY, 'Human draft')
    observe(tmp_path, f, screen, 1000)
    observe(tmp_path, f, screen, 1300)
    assert len(FilesEvents(tmp_path / 'events').pending('lead')) == 1
    assert keys(f[1]) == []


def test_recorded_pointer_is_reused_not_duplicated(tmp_path, monkeypatch):
    f = fixtures(tmp_path, monkeypatch, messages=[BODY])
    observe(tmp_path, f, QUEUED, 1000)
    observe(tmp_path, f, QUEUED, 1100)
    assert len(f[-1].unread('worker')) == 1


def test_indeterminate_pointer_write_is_not_repeated(tmp_path, monkeypatch):
    f = fixtures(tmp_path, monkeypatch)
    calls = []
    def timed_out(*a, **kw):
        calls.append(a)
        raise TimeoutError('unknown commit')
    monkeypatch.setattr(f[-1], 'deliver', timed_out)
    with pytest.raises(TimeoutError):
        observe(tmp_path, f, QUEUED, 1000)
    observe(tmp_path, f, QUEUED, 1300)
    assert len(calls) == 1


def test_cleared_notice_gets_one_redelivery_and_closes_only_its_pointer(tmp_path, monkeypatch):
    f = fixtures(tmp_path, monkeypatch, state='cleared')
    sent = []
    monkeypatch.setattr(f[0], 'send', lambda pane, body: sent.append((pane, body)))
    observe(tmp_path, f, READY, 1000)
    observe(tmp_path, f, READY, 1300)
    assert sent == [('worker', BODY)]
    assert f[-1].unread('worker') == []
    assert records(tmp_path)[0]['state'] == 'delivered'


def test_reused_session_never_redelivers(tmp_path, monkeypatch):
    f = fixtures(tmp_path, monkeypatch, state='cleared')
    monkeypatch.setattr(f[0], 'session_created', lambda _: 99)
    monkeypatch.setattr(f[0], 'send', lambda *_: pytest.fail('wrong session'))
    observe(tmp_path, f, READY, 1000)
    assert records(tmp_path)[0]['state'] == 'cleared'


def test_failed_redelivery_is_not_retried_on_next_tend(tmp_path, monkeypatch):
    f = fixtures(tmp_path, monkeypatch, state='cleared')
    calls = []
    def fail(*a):
        calls.append(a)
        raise tmux.PaneSubmissionUnverified('not observed')
    monkeypatch.setattr(f[0], 'send', fail)
    observe(tmp_path, f, READY, 1000)
    observe(tmp_path, f, READY, 1300)
    assert len(calls) == 1
    assert len(f[-1].unread('worker')) == 1
    assert len(FilesEvents(tmp_path / 'events').pending('lead')) == 1


def test_inbox_outage_still_reaches_independent_admin_event(tmp_path, monkeypatch):
    f = fixtures(tmp_path, monkeypatch)
    monkeypatch.setattr(f[-1], 'unread', lambda _: (_ for _ in ()).throw(TimeoutError()))
    observe(tmp_path, f, QUEUED, 1000)
    observe(tmp_path, f, QUEUED, 1300)
    [event] = FilesEvents(tmp_path / 'events').pending('lead')
    assert 'unread=UNKNOWN' in event.detail
    assert records(tmp_path)[0]['state'] == 'queued'


def test_attr_stripped_or_ghost_body_cannot_authorize_cleanup():
    from shantytown.triage import strip_attrs
    assert not tmux._codex_owned_input(strip_attrs(OWNED), BODY)
    assert not tmux._codex_owned_input(READY, 'Ask Codex to do anything')


def test_acknowledged_episode_rearms_only_for_new_backlog(tmp_path, monkeypatch):
    f = fixtures(tmp_path, monkeypatch, state=None, messages=['old'])
    observe(tmp_path, f, READY, 1000)
    observe(tmp_path, f, READY, 1300)
    events = FilesEvents(tmp_path / 'events')
    assert len(events.drain('lead')) == 1
    f[-1].mark_read('worker')
    observe(tmp_path, f, READY, 1400)
    f[-1].deliver('worker', 'new')
    observe(tmp_path, f, READY, 1500)
    observe(tmp_path, f, READY, 1800)
    assert len(events.drain('lead')) == 1


def test_known_failed_notice_can_unblock_a_later_sender_without_losing_old_body(tmp_path, monkeypatch):
    panes, calls = local(monkeypatch, tmp_path, [OWNED])
    with delivery.Custody(tmp_path, 'worker') as custody:
        custody.begin(BODY, 17.0)
        custody.finish('unknown')
    def capture(*a, **kw):
        if any(c[-1] == 'Enter' for c in keys(calls)):
            return BUSY
        if any(c[-1] == 'C-u' for c in keys(calls)):
            return READY
        return OWNED
    monkeypatch.setattr(panes, 'capture', capture)
    panes.send('worker', 'Next notice')
    values = {r['text']: r['state'] for r in records(tmp_path)}
    assert values == {BODY: 'cleared', 'Next notice': 'delivered'}
    assert [c[-1] for c in keys(calls)] == ['C-e', 'C-u', 'Next notice', 'Enter']


def test_one_coordinator_wake_is_backed_by_a_retained_event(tmp_path, monkeypatch):
    from shantytown import notify
    f = fixtures(tmp_path, monkeypatch)
    wakes = []
    def wake(reg, panes, worker, detail, **kw):
        assert len(FilesEvents(tmp_path / 'events').pending('lead')) == 1
        wakes.append(worker)
        raise tmux.PaneSubmissionUnverified('coordinator queued')
    monkeypatch.setattr(notify, 'wake_recipient', wake)
    observe(tmp_path, f, QUEUED, 1000)
    observe(tmp_path, f, QUEUED, 1300)
    observe(tmp_path, f, QUEUED, 1600)
    assert wakes == ['worker']
    assert len(FilesEvents(tmp_path / 'events').pending('lead')) == 1


def test_recovery_preserves_original_sender(tmp_path, monkeypatch):
    f = fixtures(tmp_path, monkeypatch, state=None)
    original = '[from reporter] Retained notice'
    with delivery.Custody(tmp_path, 'worker') as custody:
        custody.begin(original, 17.0)
        custody.finish('cleared')
    sent = []
    monkeypatch.setattr(f[0], 'send', lambda pane, text: sent.append(text))
    observe(tmp_path, f, READY, 1000)
    assert sent == [original]


def test_missing_pointer_is_not_invented_acknowledgment(tmp_path, monkeypatch):
    f = fixtures(tmp_path, monkeypatch)
    observe(tmp_path, f, QUEUED, 1000)
    for path in (tmp_path / 'inbox').glob('msg-*.json'):
        path.unlink()
    observe(tmp_path, f, QUEUED, 1300)
    assert records(tmp_path)[0]['state'] == 'queued'
    assert len(FilesEvents(tmp_path / 'events').pending('lead')) == 1


def test_explicit_receipt_acknowledgment_discharges_queued_custody(tmp_path, monkeypatch):
    f = fixtures(tmp_path, monkeypatch)
    observe(tmp_path, f, QUEUED, 1000)
    f[-1].mark_read('worker')
    observe(tmp_path, f, READY, 1300)
    assert records(tmp_path)[0]['state'] == 'acknowledged'
    assert FilesEvents(tmp_path / 'events').pending('lead') == []


def test_ambiguous_pointers_never_create_a_third_or_redeliver(tmp_path, monkeypatch):
    f = fixtures(tmp_path, monkeypatch, state='cleared', messages=[BODY, BODY])
    monkeypatch.setattr(f[0], 'send', lambda *_: pytest.fail('ambiguous pointers'))
    observe(tmp_path, f, READY, 1000)
    observe(tmp_path, f, READY, 1300)
    assert len(f[-1].unread('worker')) == 2
    assert records(tmp_path)[0]['pointer_state'] == 'ambiguous'
    assert len(FilesEvents(tmp_path / 'events').pending('lead')) == 1


# aegis-185l: a stale GOVERNOR HOLD notice stranded dearing 3h and gennaro 10h,
# and the backlog watch (re-armed only on an EMPTY backlog) never paged.

def test_queued_body_restored_to_idle_composer_unblocks_the_next_sender(tmp_path, monkeypatch):
    panes, calls = local(monkeypatch, tmp_path, [OWNED])
    with delivery.Custody(tmp_path, 'worker') as custody:
        custody.begin(BODY, 17.0)
        custody.finish('queued')
    def capture(*a, **kw):
        if any(c[-1] == 'Enter' for c in keys(calls)):
            return BUSY
        if any(c[-1] == 'C-u' for c in keys(calls)):
            return READY
        return OWNED
    monkeypatch.setattr(panes, 'capture', capture)
    panes.send('worker', 'Next notice')
    values = {r['text']: r['state'] for r in records(tmp_path)}
    assert values == {BODY: 'cleared', 'Next notice': 'delivered'}
    assert [c[-1] for c in keys(calls)] == ['C-e', 'C-u', 'Next notice', 'Enter']


def test_queued_body_still_in_codex_queue_is_not_cleared(tmp_path, monkeypatch):
    panes, calls = local(monkeypatch, tmp_path, [QUEUED])
    with delivery.Custody(tmp_path, 'worker') as custody:
        custody.begin(BODY, 17.0)
        custody.finish('queued')
    monkeypatch.setattr(panes, 'capture', lambda *a, **kw: QUEUED)
    with pytest.raises(tmux.PaneSubmissionUnverified):
        panes.send('worker', 'Next notice')
    assert not any(c[-1] in ('C-e', 'C-u') for c in keys(calls))
    assert {r['text']: r['state'] for r in records(tmp_path)}[BODY] == 'queued'


def test_superseded_notice_is_cleared_but_never_resent_or_pointed(tmp_path, monkeypatch):
    panes, calls = local(monkeypatch, tmp_path, [OWNED])
    with delivery.Custody(tmp_path, 'worker') as custody:
        custody.begin(BODY, 17.0)
        custody.finish('queued')
    assert delivery.supersede(tmp_path, lambda text: text == BODY, keep='other')
    def capture(*a, **kw):
        if any(c[-1] == 'Enter' for c in keys(calls)):
            return BUSY
        if any(c[-1] == 'C-u' for c in keys(calls)):
            return READY
        return OWNED
    monkeypatch.setattr(panes, 'capture', capture)
    panes.send('worker', 'Lifted notice')
    values = {r['text']: r['state'] for r in records(tmp_path)}
    assert values == {BODY: 'superseded', 'Lifted notice': 'delivered'}
    f = fixtures(tmp_path, monkeypatch, state=None)
    sent = len(keys(f[1]))
    observe(tmp_path, f, READY, 1000)
    assert f[-1].unread('worker') == []          # no pointer for superseded text
    assert len(keys(f[1])) == sent               # and nothing typed again


def test_supersede_marks_only_unfinished_stale_bodies_and_keeps_the_current_one(tmp_path):
    for text, state in [('HOLD a', 'queued'), ('HOLD b', 'unknown'), ('HOLD c', 'delivered'),
                        ('mail', 'queued'), ('HOLD now', 'queued')]:
        with delivery.Custody(tmp_path, 'worker') as custody:
            custody.begin(text, 17.0)
            custody.finish(state)
    done = delivery.supersede(tmp_path, lambda t: t.startswith('HOLD'), keep='HOLD now')
    values = {r['text']: r['state'] for r in records(tmp_path)}
    assert len(done) == 2
    assert values == {'HOLD a': 'superseded', 'HOLD b': 'superseded', 'HOLD c': 'delivered',
                      'mail': 'queued', 'HOLD now': 'queued'}
    assert delivery.supersede(tmp_path / 'absent', lambda t: True, keep='') == []


def stranded(tmp_path, monkeypatch, *, state='queued'):
    from shantytown import notify
    f = fixtures(tmp_path, monkeypatch, state=state)
    wakes = []
    monkeypatch.setattr(notify, 'wake_recipient', lambda reg, panes, worker, detail, **kw:
                        wakes.append(detail))
    return f, wakes


def stranded_events(tmp_path):
    return [e for e in FilesEvents(tmp_path / 'events').pending('lead')
            if 'unsubmitted in an idle composer' in e.detail
            or 'consecutive sends not delivered' in e.detail]


def test_owned_notice_in_idle_composer_pages_lead_after_15_minutes(tmp_path, monkeypatch):
    import time
    f, wakes = stranded(tmp_path, monkeypatch)
    t = time.time()
    observe(tmp_path, f, OWNED, t)
    observe(tmp_path, f, OWNED, t + delivery.STRANDED_SECONDS - 1)
    assert stranded_events(tmp_path) == []
    observe(tmp_path, f, OWNED, t + delivery.STRANDED_SECONDS)
    [event] = stranded_events(tmp_path)
    assert event.reason == 'delivery-stalled'
    assert BODY not in event.detail
    assert 'idle composer' in event.detail
    assert len([w for w in wakes if 'idle composer' in w]) == 1
    observe(tmp_path, f, OWNED, t + 2 * delivery.STRANDED_SECONDS)
    assert len(stranded_events(tmp_path)) == 1    # one page per episode
    # The composer empties, then the same body strands again: a new episode.
    observe(tmp_path, f, READY, t + 2 * delivery.STRANDED_SECONDS + 1)
    observe(tmp_path, f, OWNED, t + 3 * delivery.STRANDED_SECONDS)
    observe(tmp_path, f, OWNED, t + 4 * delivery.STRANDED_SECONDS)
    assert len(stranded_events(tmp_path)) == 2
    assert keys(f[1]) == []                        # the watch never types


@pytest.mark.parametrize('screen', [BUSY.replace(READY, OWNED), OWNED.replace(BODY, 'Human draft'), READY])
def test_busy_pane_foreign_draft_or_empty_composer_never_pages(tmp_path, monkeypatch, screen):
    import time
    f, wakes = stranded(tmp_path, monkeypatch, state='delivered')
    t = time.time()
    for k in range(3):
        observe(tmp_path, f, screen, t + k * delivery.STRANDED_SECONDS)
    assert stranded_events(tmp_path) == [] and wakes == []


def test_repeated_undelivered_sends_page_once_and_rearm_after_a_delivery(tmp_path, monkeypatch):
    import time
    f, wakes = stranded(tmp_path, monkeypatch, state=None)
    for n in range(delivery.FAILED_SENDS - 1):
        with delivery.Custody(tmp_path, 'worker') as custody:
            custody.begin(f'notice {n}', 17.0)
            custody.finish('queued')
    t = time.time()  # after the sends: age is measured from the first of them
    observe(tmp_path, f, BUSY, t + delivery.STRANDED_SECONDS)
    assert stranded_events(tmp_path) == []        # four is below the threshold
    with delivery.Custody(tmp_path, 'worker') as custody:
        custody.begin('notice 4', 17.0)
        custody.finish('unknown')
    observe(tmp_path, f, BUSY, t + delivery.STRANDED_SECONDS)
    [event] = stranded_events(tmp_path)
    assert '5 consecutive sends not delivered' in event.detail
    observe(tmp_path, f, BUSY, t + 2 * delivery.STRANDED_SECONDS)
    assert len(stranded_events(tmp_path)) == 1
    with delivery.Custody(tmp_path, 'worker') as custody:
        custody.begin('delivered one', 17.0)
        custody.finish('delivered')
    observe(tmp_path, f, BUSY, t + 3 * delivery.STRANDED_SECONDS)
    assert len(stranded_events(tmp_path)) == 1    # a delivery ends the episode


def test_capture_error_while_clearing_keeps_a_superseded_body_terminal(tmp_path, monkeypatch):
    # Review of #386: failed() persists `unknown` before it captures the pane.
    # A capture that raises must not leave the old notice resubmittable.
    panes, calls = local(monkeypatch, tmp_path, [OWNED])
    with delivery.Custody(tmp_path, 'worker') as custody:
        custody.begin(BODY, 17.0)
        custody.finish('superseded')
    def capture(*a, **kw):
        raise OSError('pane unreadable')
    monkeypatch.setattr(panes, 'capture', capture)
    with delivery.Custody(tmp_path, 'worker') as custody:
        with pytest.raises(OSError):
            custody.clear_previous(panes, OWNED)
    assert {r['text']: r['state'] for r in records(tmp_path)} == {BODY: 'superseded'}
    assert keys(calls) == []
