"""Observe native Codex transcript call IDs without guessing process outcomes.

The native shell hook currently loses exit status and uses an inner exec ID.
Transcript cells have their own stable call IDs. Keep that granularity explicit;
never join them by time, agent, stdout or command text. This recorder is optional
and cannot change a tool result or enforcement.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import stat as stat_mode
from datetime import datetime

_LIMIT = 2 * 1024 * 1024
_SCHEMA = '''
CREATE TABLE IF NOT EXISTS native_trace_streams (
 session TEXT, agent TEXT, path TEXT, inode INTEGER, offset INTEGER,
 PRIMARY KEY(session, agent));
CREATE TABLE IF NOT EXISTS native_trace_events (
 session TEXT, agent TEXT, call_id TEXT, kind TEXT, item TEXT, row_json TEXT,
 state TEXT NOT NULL DEFAULT 'pending', PRIMARY KEY(session,agent,call_id,kind));
'''


def _stamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, AttributeError, TypeError):
        return None


def _item(conn, session, agent, action_stamp):
    try:
        row = conn.execute('SELECT task,paired_start,ts FROM task_contexts WHERE session=? AND agent=? '
                           'ORDER BY id DESC LIMIT 1', (session, agent)).fetchone()
        return row[0] if row and row[1] == 1 and row[2] <= action_stamp else None
    except sqlite3.Error:
        return None


def _emit(conn, session, agent, path):
    rows = conn.execute('SELECT call_id,kind,row_json FROM native_trace_events '
                        'WHERE session=? AND agent=? AND state="pending" ORDER BY rowid', (session, agent)).fetchall()
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    for call, kind, body in rows:
        if kind == 'action_outcome':
            action = conn.execute('SELECT state FROM native_trace_events WHERE '
                                  'session=? AND agent=? AND call_id=? AND kind="action"',
                                  (session,agent,call)).fetchone()
            if action is None or action[0] != 'delivered':
                continue
        # Durable attempt before an external append: interruption is UNKNOWN,
        # never a reason to blindly resend an event into an additive spool.
        claim = conn.execute('UPDATE native_trace_events SET state="attempted" WHERE '
                             'session=? AND agent=? AND call_id=? AND kind=? AND state="pending"',
                             (session,agent,call,kind))
        conn.commit()
        if claim.rowcount != 1:
            continue
        fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            data = (body + '\n').encode()
            if os.write(fd, data) != len(data):
                raise OSError('short trace write')
            os.fsync(fd)
        finally:
            os.close(fd)
        conn.execute('UPDATE native_trace_events SET state="delivered" WHERE '
                     'session=? AND agent=? AND call_id=? AND kind=?', (session,agent,call,kind))
        conn.commit()


def capture(conn, payload, agent, spool=None):
    """Incremental, session-validated transcript observation; payload text is private."""
    if payload.get('hook_event_name') not in ('PreToolUse','PostToolUse','PostToolUseFailure','Stop'):
        return
    session = payload.get('session_id')
    source = payload.get('transcript_path')
    if not isinstance(session, str) or not session or not isinstance(source, str):
        return
    path = Path(source)
    try:
        if not stat_mode.S_ISREG(path.stat().st_mode):
            return
        with path.open('rb') as stream:
            first = json.loads(stream.readline(_LIMIT))
            meta = first.get('payload', {})
            if (first.get('type') != 'session_meta' or
                    (meta.get('session_id') or meta.get('id')) != session):
                return
            conn.executescript(_SCHEMA)
            stat = os.fstat(stream.fileno())
            saved = conn.execute('SELECT path,inode,offset FROM native_trace_streams '
                                 'WHERE session=? AND agent=?', (session,agent)).fetchone()
            if saved is None:
                # Adopt the current stream boundary, never attribute historic
                # calls to today's task. The next completed controls follow a
                # normal task-boundary priming call.
                conn.execute('INSERT OR IGNORE INTO native_trace_streams VALUES (?,?,?,?,?)',
                             (session,agent,str(path),stat.st_ino,stat.st_size))
                conn.commit()
                return
            offset = saved[2]
            if saved and (saved[0] != str(path) or saved[1] != stat.st_ino or offset > stat.st_size):
                return   # replacement/truncation is UNKNOWN; never restart and replay
            stream.seek(offset)
            stop = min(stat.st_size, offset + _LIMIT)
            while stream.tell() < stop:
                before = stream.tell()
                line = stream.readline(_LIMIT + 1)
                if not line.endswith(b'\n') or len(line) > _LIMIT:
                    stream.seek(before)
                    break  # partial or oversized row remains UNKNOWN
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get('type') != 'response_item':
                    continue
                row = entry.get('payload', {})
                kind = row.get('type')
                call = row.get('call_id')
                if not isinstance(call, str) or not call:
                    continue
                stamp = _stamp(entry.get('timestamp'))
                if stamp is None:
                    continue
                if kind == 'custom_tool_call' and row.get('name') == 'exec':
                    item = _item(conn,session,agent,stamp)
                    event = {'kind':'action','action_id':call,'agent':agent,'session':session,
                             'ts':stamp,'target_class':'unknown','trace_source':'codex-transcript',
                             'granularity':'tool-call','tool':'exec','tenant':os.environ.get('BOBBIN_ROLE') or 'unknown'}
                    if item:
                        event['item'] = item
                        event['item_source'] = 'confirmed-session-task'
                    conn.execute('INSERT OR IGNORE INTO native_trace_events '
                                 '(session,agent,call_id,kind,item,row_json) VALUES (?,?,?,?,?,?)',
                                 (session,agent,call,'action',item,json.dumps(event)))
                elif kind == 'custom_tool_call_output':
                    action = conn.execute('SELECT item FROM native_trace_events WHERE '
                                          'session=? AND agent=? AND call_id=? AND kind="action"',
                                          (session,agent,call)).fetchone()
                    if action is None:
                        continue  # exact-ID orphan cannot invent an action
                    # Native exec-cell output has no typed process status. Even
                    # JSON-looking stdout cannot supply it: cell code can print
                    # arbitrary values. No event-name or text inference.
                    event = {'kind':'action_outcome','action_id':call,'agent':agent,'session':session,
                             'ts':stamp,'outcome':'unknown','trace_source':'codex-transcript',
                             'granularity':'tool-call','reason':'native-process-status-unavailable',
                             'tenant':os.environ.get('BOBBIN_ROLE') or 'unknown'}
                    if action[0]:
                        event['item'] = action[0]
                        event['item_source'] = 'confirmed-session-task'
                    conn.execute('INSERT OR IGNORE INTO native_trace_events '
                                 '(session,agent,call_id,kind,item,row_json) VALUES (?,?,?,?,?,?)',
                                 (session,agent,call,'action_outcome',action[0],json.dumps(event)))
            conn.execute('INSERT OR REPLACE INTO native_trace_streams VALUES (?,?,?,?,?)',
                         (session,agent,str(path),stat.st_ino,stream.tell()))
            conn.commit()
        _emit(conn,session,agent,Path(spool) if spool else Path.home()/'.local/state/yupana/metrics.jsonl')
    except (OSError, ValueError, TypeError, sqlite3.Error):
        # Attempt journal retains failures; no stdout/stderr or secrets leak.
        return
