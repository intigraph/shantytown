"""Late native consumption can complete one receipt, never resend its body."""
import copy
import json
import time
from datetime import datetime, timezone

import pytest

from shantytown.codex_submission import native_proof
from shantytown.dispatch import Dispatcher, SendUnverified
from shantytown.dispatch_binding import binding_for
from shantytown.dispatch_receipts import ReceiptConflict
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.tmux import NullPanes, Tmux

SESSION = '11111111-1111-4111-8111-111111111111'
TURN = '22222222-2222-4222-8222-222222222222'
BODY = 'exact  body [st serve:fixture worker:worker]'


def rows(text=BODY):
    at = datetime.now(timezone.utc).isoformat()
    return [dict(type='event_msg', timestamp=at, payload=dict(type='task_started', turn_id=TURN)),
            dict(type='event_msg', timestamp=at, payload=dict(type='item_completed',
                 thread_id=SESSION, turn_id=TURN, item=dict(type='UserMessage',
                 content=[dict(type='text', text=text, text_elements=[])])))]


def prove(values):
    return native_proof([json.dumps(x) for x in values], BODY, SESSION, time.time() - 10)


def test_exact_started_native_user_message_is_consumption():
    assert prove(rows())['kind'] == 'codex-native-user'


@pytest.mark.parametrize('change', ['no-start', 'queue', 'quote', 'wrong-turn',
    'wrong-thread', 'old', 'future', 'normalized', 'duplicate', 'duplicate-start'])
def test_incomplete_ambiguous_or_other_evidence_is_not_consumption(change):
    values = rows()
    if change == 'no-start': values.pop(0)
    elif change == 'queue': values[1]['payload']['type'] = 'user_message'
    elif change == 'quote': values[1]['payload']['item']['type'] = 'CommandExecution'
    elif change == 'wrong-turn': values[1]['payload']['turn_id'] = SESSION
    elif change == 'wrong-thread': values[1]['payload']['thread_id'] = TURN
    elif change == 'old': values[0]['timestamp'] = '2000-01-01T00:00:00Z'
    elif change == 'future': values[1]['timestamp'] = '2100-01-01T00:00:00Z'
    elif change == 'normalized': values = rows(BODY.replace('  ', ' '))
    elif change == 'duplicate': values += copy.deepcopy(values)
    elif change == 'duplicate-start': values.append(copy.deepcopy(values[0]))
    assert prove(values) is None


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / 'town'
    (root / 'crew').mkdir(parents=True)
    workspace = str(tmp_path / 'workspace')
    (root / 'crew/worker.json').write_text(json.dumps(dict(
        pane='%5', harness='codex', workspace=workspace)))
    (root / 'context_budget').mkdir()
    settings = tmp_path / 'codex/config.toml'
    path = settings.parent / 'sessions/2026/11/12' / f'rollout-2026-11-12T00-00-00-{SESSION}.jsonl'
    path.parent.mkdir(parents=True)
    header = dict(type='session_meta', payload=dict(id=SESSION, cwd=workspace))
    path.write_text(json.dumps(header) + '\n')
    hook = root / 'context_budget/worker.json'
    hook.write_text(json.dumps(dict(payload=dict(session_id=SESSION, transcript_path=str(path)))))
    monkeypatch.setattr('shantytown.session_budget.current_session', lambda *a: SESSION)
    adapter = Tmux(socket='test-only', root=root)
    runtime = ['fixture-process']
    monkeypatch.setattr(adapter, 'runtime_identity', lambda _: runtime[0])
    monkeypatch.setattr(adapter, 'session_created', lambda _: 123)
    monkeypatch.setattr(adapter, 'foreground', lambda _: 'codex')
    monkeypatch.setattr(adapter, 'cmdline', lambda _: f'CODEX_HOME={settings.parent} codex')

    class Panes(NullPanes):
        def runtime_identity(self, pane): return runtime[0]
        def session_created(self, pane): return 123
        def send(self, pane, text): self.sent.append((pane, text))
        def observed_submission(self, *args): return adapter.observed_submission(*args)

    panes = Panes(screen='')
    tracker = FilesTracker(root / 'items')
    tracker.update('work-1', title='bounded work', status='open')
    registry = FilesRegistry(root / 'crew')
    binding = binding_for(root, tracker, registry, panes)
    dispatcher = Dispatcher(registry, tracker, panes, binding=binding)
    monkeypatch.setattr('shantytown.dispatch_binding.time.sleep', lambda _: None)
    return dispatcher, binding, tracker, panes, path, header, runtime, hook


def test_late_real_adapter_proof_completes_once_without_second_send(world):
    d, binding, tracker, panes, path, header, runtime, hook = world
    with pytest.raises(SendUnverified): d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    assert row['submission'] is row['assignment'] is None
    path.write_text('\n'.join(json.dumps(x) for x in [header, *rows(row['text'])]) + '\n')
    before = {p: p.read_bytes() for p in path.parents[4].rglob('*.json')}
    assert not binding.reconcile(row['id'])['execution_authorized']
    assert before == {p: p.read_bytes() for p in before}
    result = d.complete('work-1', 'worker', receipt=row['id'])
    assert result['execution_authorized'] and tracker.get('work-1').revision == 2
    assert binding.store.read(row['id'])['submission']['source']['kind'] == 'codex-native-user'
    assert len(panes.sent) == 1
    assert d.complete('work-1', 'worker', receipt=row['id'])['execution_authorized']
    assert tracker.get('work-1').revision == 2 and len(panes.sent) == 1


@pytest.mark.parametrize('change', ['runtime', 'workspace', 'session', 'symlink', 'outside', 'header'])
def test_late_completion_keeps_identity_and_file_fences(world, change):
    d, binding, tracker, panes, path, header, runtime, hook = world
    with pytest.raises(SendUnverified): d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    if change == 'workspace': header['payload']['cwd'] += '/other'
    if change == 'header': header = []
    path.write_text('\n'.join(json.dumps(x) for x in [header, *rows(row['text'])]) + '\n')
    if change == 'runtime': runtime[0] = 'replacement-process'
    if change == 'session':
        hook.write_text(json.dumps(dict(payload=dict(session_id=TURN, transcript_path=str(path)))))
    if change in ('symlink', 'outside'):
        moved = path.with_name('other.jsonl')
        path.rename(moved)
        if change == 'symlink': path.symlink_to(moved)
        else: hook.write_text(json.dumps(dict(payload=dict(session_id=SESSION, transcript_path=str(moved)))))
    with pytest.raises(ReceiptConflict): d.complete('work-1', 'worker', receipt=row['id'])
    assert tracker.get('work-1').revision == 1 and len(panes.sent) == 1
    assert binding.store.read(row['id'])['submission'] is None


def test_exhausted_tail_cannot_hide_duplicate_consumption(world, monkeypatch):
    d, binding, tracker, panes, path, header, runtime, hook = world
    with pytest.raises(SendUnverified): d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    values = [header, *rows(row['text']), dict(padding='x' * 4000), *rows(row['text'])]
    path.write_text('\n'.join(json.dumps(x) for x in values) + '\n')
    monkeypatch.setattr('shantytown.codex_submission.CAP', 3000)
    with pytest.raises(ReceiptConflict): d.complete('work-1', 'worker', receipt=row['id'])
    assert tracker.get('work-1').revision == 1 and len(panes.sent) == 1
