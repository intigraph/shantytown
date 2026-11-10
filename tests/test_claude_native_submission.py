"""Native consumption evidence is distinct from visible text and queue custody."""
import copy
import json
import time
from datetime import datetime, timezone

import pytest

from shantytown.claude_submission import native_proof

SESSION = '11111111-1111-4111-8111-111111111111'
COMMAND = '22222222-2222-4222-8222-222222222222'
DELIVERY = '33333333-3333-4333-8333-333333333333'
BODY = 'exact request with preserved  whitespace [unique receipt]'


def records():
    at = datetime.now(timezone.utc).isoformat()
    base = dict(sessionId=SESSION, timestamp=at)
    return [dict(base, type='queue-operation', operation='enqueue', content=BODY),
            dict(base, type='queue-operation', operation='remove', content=BODY,
                 reason='absorbed_mid_turn', commandUuid=COMMAND, deliveryId=DELIVERY),
            dict(base, type='attachment', renderedRole='system', attachment=dict(
                type='queued_command', prompt=BODY, commandMode='prompt', humanTurn=True,
                origin={'kind':'human'}, source_uuid=COMMAND, delivery_id=DELIVERY))]


def proof(rows, *, body=BODY, session=SESSION, created=None):
    return native_proof([json.dumps(r) for r in rows], body, session,
                        time.time() - 5 if created is None else created)


def test_busy_exact_consumption_matches_both_native_ids():
    result = proof(records())
    assert result['kind'] == 'claude-native-absorbed-command'
    assert result['command_uuid'] == COMMAND and result['delivery_id'] == DELIVERY
    assert BODY not in json.dumps(result)


@pytest.mark.parametrize('omit', [0, 1, 2])
def test_queue_or_attachment_alone_is_not_consumption(omit):
    rows = records()
    rows.pop(omit)
    assert proof(rows) is None


@pytest.mark.parametrize('change', ['session', 'body', 'old', 'future', 'id', 'sidechain', 'reason', 'origin'])
def test_scope_and_native_chain_must_match(change):
    rows = records()
    if change == 'session':
        rows[2]['sessionId'] = COMMAND
    elif change == 'body':
        rows[2]['attachment']['prompt'] += ' '
    elif change == 'old':
        rows[1]['timestamp'] = '2000-01-01T00:00:00Z'
    elif change == 'future':
        rows[1]['timestamp'] = '2100-01-01T00:00:00Z'
    elif change == 'id':
        rows[2]['attachment']['delivery_id'] = COMMAND
    elif change == 'sidechain':
        rows[2]['isSidechain'] = True
    elif change == 'reason':
        rows[1]['reason'] = 'discarded'
    elif change == 'origin':
        rows[2]['attachment']['origin'] = {'kind':'tool'}
    assert proof(rows) is None


def test_quotes_tool_results_and_duplicate_consumption_do_not_prove_send():
    rows = records()
    assert proof([dict(rows[0], type='user', uuid=COMMAND,
                       message={'role':'user', 'content':[{'type':'tool_result', 'content':BODY}]})]) is None
    assert proof([dict(rows[0], type='assistant', message={'role':'assistant','content':BODY})]) is None
    assert proof(rows + copy.deepcopy(rows)) is None


def test_exact_native_user_input_is_positive_but_normalization_is_not():
    row = dict(records()[0], type='user', uuid=COMMAND,
               message={'role':'user','content':[{'type':'text','text':BODY}]})
    assert proof([row])['kind'] == 'claude-native-user'
    assert proof([row], body=BODY.replace('  ', ' ')) is None


def test_observer_binds_hook_stats_workspace_and_owned_transcript(tmp_path, monkeypatch):
    from shantytown import claude_submission as native, stats
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    root = tmp_path / 'town'
    (root / 'crew').mkdir(parents=True)
    (root / 'crew/worker.json').write_text(json.dumps(dict(
        pane='worker-pane', workspace=str(tmp_path / 'workspace'), harness='claude')))
    (root / 'context_budget').mkdir()
    transcript = (tmp_path / 'home/.claude/projects'
                  / stats._claude_project_dir(str(tmp_path / 'workspace')) / (SESSION + '.jsonl'))
    transcript.parent.mkdir(parents=True)
    transcript.write_text('\n'.join(json.dumps(r) for r in records()) + '\n')
    hook = root / 'context_budget/worker.json'
    hook.write_text(json.dumps({'payload':{'session_id':SESSION, 'transcript_path':str(transcript)}}))
    monkeypatch.setattr('shantytown.session_budget.current_session', lambda *a: SESSION)
    assert native.observe(root, 'worker', BODY, time.time() - 5)['kind'] == 'claude-native-absorbed-command'
    monkeypatch.setattr('shantytown.session_budget.current_session', lambda *a: COMMAND)
    assert native.observe(root, 'worker', BODY, time.time() - 5) is None
    monkeypatch.setattr('shantytown.session_budget.current_session', lambda *a: SESSION)
    retained = transcript.with_suffix('.retained')
    transcript.rename(retained)
    transcript.symlink_to(retained)
    assert native.observe(root, 'worker', BODY, time.time() - 5) is None
