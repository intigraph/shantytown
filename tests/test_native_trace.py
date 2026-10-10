"""Native transcript IDs, unknown process status, scope and single-attempt delivery."""
import json
import sqlite3
from shantytown import native_trace


def setup(tmp_path, rows):
    path=tmp_path/'native.jsonl'
    header={'type':'session_meta','payload':{'session_id':'session'}}
    path.write_text(json.dumps(header)+'\n')
    conn=sqlite3.connect(tmp_path/'stats.sqlite')
    conn.execute('CREATE TABLE task_contexts(id INTEGER,session TEXT,agent TEXT,task TEXT,paired_start INTEGER DEFAULT 1)')
    conn.execute('INSERT INTO task_contexts(id,session,agent,task) VALUES (1,"session","worker","work-first")')
    conn.commit()
    payload={'session_id':'session','transcript_path':str(path),'hook_event_name':'PostToolUse',
             'tool_use_id':'exec-inner-id','tool_response':''}
    spool=tmp_path/'spool.jsonl'
    native_trace.capture(conn,payload,'worker',spool)
    with path.open('a') as f:
        f.write(''.join(json.dumps(x)+'\n' for x in rows))
    return conn,payload,path,spool


def call(ident='call-outer'):
    return {'type':'response_item','timestamp':'2026-10-10T00:00:00Z',
            'payload':{'type':'custom_tool_call','name':'exec','call_id':ident,'input':'private command'}}


def result(ident='call-outer'):
    return {'type':'response_item','timestamp':'2026-10-10T00:00:01Z',
            'payload':{'type':'custom_tool_call_output','call_id':ident,
                       'output':[{'type':'input_text','text':'{"exit_code":0,"token":"PRIVATE_SENTINEL"}'}]}}


def read(spool):
    return [json.loads(x) for x in spool.read_text().splitlines()] if spool.exists() else []


def test_exact_transcript_pair_and_text_is_never_exit_status(tmp_path):
    conn,payload,path,spool=setup(tmp_path,[call(),result()])
    native_trace.capture(conn,payload,'worker',spool)
    rows=read(spool)
    assert [x['kind'] for x in rows]==['action','action_outcome']
    assert {x['action_id'] for x in rows}=={'call-outer'}
    assert rows[1]['outcome']=='unknown'
    assert {x['item'] for x in rows}=={'work-first'}
    assert 'PRIVATE_SENTINEL' not in spool.read_text()
    native_trace.capture(conn,payload,'worker',spool)
    assert read(spool)==rows


def test_outcome_keeps_original_scope_after_next_task(tmp_path):
    conn,payload,path,spool=setup(tmp_path,[call()])
    native_trace.capture(conn,payload,'worker',spool)
    conn.execute('INSERT INTO task_contexts(id,session,agent,task) VALUES (2,"session","worker","work-next")');conn.commit()
    with path.open('a') as f:f.write(json.dumps(result())+'\n')
    native_trace.capture(conn,payload,'worker',spool)
    assert read(spool)[1]['item']=='work-first'


def test_session_mismatch_and_orphan_cannot_invent_action(tmp_path):
    conn,payload,path,spool=setup(tmp_path,[result('wrong-call')])
    native_trace.capture(conn,payload,'worker',spool);assert read(spool)==[]
    payload['session_id']='other'
    native_trace.capture(conn,payload,'worker',spool);assert read(spool)==[]


def test_partial_completion_waits_for_the_actual_line(tmp_path):
    conn,payload,path,spool=setup(tmp_path,[call()])
    partial=json.dumps(result())
    with path.open('a') as f:f.write(partial)
    native_trace.capture(conn,payload,'worker',spool);assert len(read(spool))==1
    with path.open('a') as f:f.write('\n')
    payload['hook_event_name']='Stop'
    native_trace.capture(conn,payload,'worker',spool);assert len(read(spool))==2


def test_write_failure_is_not_blindly_retried(tmp_path,monkeypatch):
    conn,payload,path,spool=setup(tmp_path,[call(),result()])
    original=native_trace.os.write
    def fail(fd,data):raise OSError('fixture')
    monkeypatch.setattr(native_trace.os,'write',fail)
    native_trace.capture(conn,payload,'worker',spool)
    monkeypatch.setattr(native_trace.os,'write',original)
    native_trace.capture(conn,payload,'worker',spool)
    rows=read(spool)
    assert rows==[]
    assert conn.execute('SELECT state FROM native_trace_events WHERE kind="action"').fetchone()[0]=='attempted'


def test_first_adoption_never_scopes_historical_calls_to_current_work(tmp_path):
    conn,payload,path,spool=setup(tmp_path,[])
    conn.execute('DELETE FROM native_trace_streams');conn.commit()
    with path.open('a') as f:f.write(json.dumps(call())+'\n'+json.dumps(result())+'\n')
    native_trace.capture(conn,payload,'worker',spool)
    assert read(spool)==[]


def test_unpaired_task_declaration_does_not_claim_scope(tmp_path):
    conn,payload,path,spool=setup(tmp_path,[])
    conn.execute('INSERT INTO task_contexts VALUES (2,"session","worker","unconfirmed-next",0)');conn.commit()
    with path.open('a') as f:f.write(json.dumps(call())+'\n'+json.dumps(result())+'\n')
    native_trace.capture(conn,payload,'worker',spool)
    assert all('item' not in row for row in read(spool))
