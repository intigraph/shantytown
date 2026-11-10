"""Actual terminal/native reader + initial bound dispatch, without live keys."""
import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from shantytown import stats, tmux
from shantytown.dispatch import Dispatcher, SendUnverified
from shantytown.dispatch_binding import binding_for
from shantytown.dispatch_receipts import ReceiptConflict
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.tmux import NullPanes

SESSION = '11111111-1111-4111-8111-111111111111'
UUID = '22222222-2222-4222-8222-222222222222'


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    root = tmp_path / 'town'
    (root / 'crew').mkdir(parents=True)
    workspace = str(tmp_path / 'workspace')
    (root / 'crew/worker.json').write_text(json.dumps(dict(
        pane='%5', harness='claude', workspace=workspace)))
    (root / 'context_budget').mkdir()
    transcript = (tmp_path / 'home/.claude/projects' /
                  stats._claude_project_dir(workspace) / (SESSION + '.jsonl'))
    transcript.parent.mkdir(parents=True)
    transcript.write_text('')
    (root / 'context_budget/worker.json').write_text(json.dumps(dict(payload=dict(
        session_id=SESSION, transcript_path=str(transcript)))))
    monkeypatch.setattr('shantytown.session_budget.current_session', lambda *a: SESSION)
    monkeypatch.setattr(tmux.time, 'sleep', lambda _: None)
    monkeypatch.setattr(tmux, '_journal_send', lambda *a: None)
    keys = []
    monkeypatch.setattr(tmux.subprocess, 'run', lambda argv, **kw:
                        (keys.append(argv) or SimpleNamespace(returncode=0, stdout='')))
    adapter = tmux.Tmux(socket='test-only', root=root)
    state = dict(runtime='fixture-process', session=123, kind='user', polls=0)
    monkeypatch.setattr(adapter, '_refuse_in_mode', lambda *a, **k: None)
    monkeypatch.setattr(adapter, 'foreground', lambda _: '2.1.322')
    monkeypatch.setattr(adapter, 'cmdline', lambda _: 'claude --settings /fixture/settings.json')
    monkeypatch.setattr(adapter, 'capture', lambda *a, **k: '❯ ')
    monkeypatch.setattr(adapter, '_claude_history', lambda _: '❯ ')
    monkeypatch.setattr(adapter, 'session_created', lambda _: state['session'])
    monkeypatch.setattr(adapter, 'runtime_identity', lambda _: state['runtime'])
    tracker = FilesTracker(root / 'items')
    tracker.update('work-1', title='Exact multiline request\nwith whitespace', status='open')

    class Panes(NullPanes):
        def runtime_identity(self, pane):
            return adapter.runtime_identity(pane)

        def session_created(self, pane):
            return adapter.session_created(pane)

        def send(self, pane, text):
            self.sent.append((pane, text))
            # Exact-body terminal echo is absent, as in the measured Mac failure.
            assert adapter.send(pane, text) is None
            self.body = text

        def observed_submission(self, pane, text, session, created, runtime, worker):
            state['polls'] += 1
            if state['polls'] == 2:
                row = dict(type='user', sessionId=SESSION, uuid=UUID,
                           timestamp=datetime.now(timezone.utc).isoformat(),
                           message=dict(role='user', content=text))
                if state['kind'] == 'queue':
                    row.update(type='queue-operation', operation='enqueue', content=text)
                elif state['kind'] == 'quote':
                    row['message']['content'] = [dict(type='tool_result', content=text)]
                elif state['kind'] == 'wrong-session':
                    row['sessionId'] = UUID
                elif state['kind'] == 'runtime':
                    state['runtime'] = 'replacement-process'
                elif state['kind'] == 'task':
                    tracker.update('work-1', title='changed task')
                transcript.write_text(json.dumps(row) + '\n')
            return adapter.observed_submission(pane, text, session, created, runtime, worker)

    panes = Panes(screen='')
    binding = binding_for(root, tracker, FilesRegistry(root / 'crew'), panes)
    dispatcher = Dispatcher(FilesRegistry(root / 'crew'), tracker, panes, binding=binding)
    return dispatcher, binding, tracker, panes, state, keys


def test_initial_go_observes_delayed_native_user_and_claims_once(world):
    d, binding, tracker, panes, state, keys = world
    plan = d.go('work-1', 'worker')
    row = binding.store.read(plan.receipt_id)
    assert state['polls'] == 2
    assert row['submission']['source']['kind'] == 'claude-native-user'
    assert row['submission']['source']['body_sha256'] == hashlib.sha256(plan.text.encode()).hexdigest()
    assert row['assignment'] and tracker.get('work-1').revision == 2
    assert binding.reconcile(plan.receipt_id)['execution_authorized']
    assert len(panes.sent) == sum(k[-1] == 'Enter' for k in keys) == 1
    assert d.go('work-1', 'worker').replayed
    assert len(panes.sent) == 1 and tracker.get('work-1').revision == 2


@pytest.mark.parametrize('kind', ['queue', 'quote', 'wrong-session', 'runtime', 'task'])
def test_initial_native_unknown_or_changed_scope_never_claims_or_resends(world, kind):
    d, binding, tracker, panes, state, keys = world
    state['kind'] = kind
    with pytest.raises((SendUnverified, ReceiptConflict)):
        d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    assert row['state'] == 'prepared' and row['submission'] is row['assignment'] is None
    assert tracker.get('work-1').assignee is None
    assert tracker.get('work-1').revision == (2 if kind == 'task' else 1)
    assert state['polls'] <= 11
    assert len(panes.sent) == sum(k[-1] == 'Enter' for k in keys) == 1
    with pytest.raises(ReceiptConflict):
        d.go('work-1', 'worker')
    assert len(panes.sent) == 1


def test_elapsed_budget_stops_observation_without_claim(world, monkeypatch):
    d, binding, tracker, panes, state, keys = world
    clock = iter([0, 6])
    monkeypatch.setattr('shantytown.dispatch_binding.time.monotonic', lambda: next(clock))
    with pytest.raises(SendUnverified):
        d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    assert state['polls'] == 1
    assert row['submission'] is row['assignment'] is None
    assert tracker.get('work-1').revision == 1
    assert len(panes.sent) == sum(k[-1] == 'Enter' for k in keys) == 1
