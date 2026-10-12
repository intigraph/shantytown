"""A runtime-owned zero is different from an absent/partial/foreign read."""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import threading
import time
from types import SimpleNamespace

import pytest
from shantytown import codex_shells as shells, notify, cli

THREAD = '00000000-0000-0000-0000-000000000001'


def terminal(process):
    return dict(processId=process, itemId='item-' + process, command='sleep', cwd='/workspace')


class Client:
    def __init__(self, pages, *, loaded=None):
        self.pages = iter(pages)
        self.loaded = loaded or dict(data=[THREAD], nextCursor=None)
        self.methods = []
    def send(self, value):
        self.methods.append(value['method'])
    def request(self, number, method, params):
        self.methods.append(method)
        if method == 'initialize': return {}
        if method == 'thread/loaded/list': return self.loaded
        assert method == 'thread/backgroundTerminals/list'
        assert params['threadId'] == THREAD
        return next(self.pages)


@pytest.mark.parametrize('rows,expected', [([], 0), ([terminal('42')], 1)])
def test_complete_native_zero_and_positive(rows, expected):
    client = Client([dict(data=rows, nextCursor=None)])
    assert shells._count(client, THREAD) == expected
    assert set(client.methods) <= {'initialize', 'initialized', 'thread/loaded/list', 'thread/backgroundTerminals/list'}


def test_pagination_is_complete_not_first_page_zero():
    client = Client([dict(data=[], nextCursor='more'), dict(data=[terminal('42')], nextCursor=None)])
    assert shells._count(client, THREAD) == 1


@pytest.mark.parametrize('pages', [
    [dict(data=[])], [dict(data={}, nextCursor=None)],
    [dict(data=[{}], nextCursor=None)],
    [dict(data=[terminal('42'), terminal('42')], nextCursor=None)],
    [dict(data=[], nextCursor=True)],
    [dict(data=[], nextCursor='loop'), dict(data=[], nextCursor='loop')],
    [dict(data=[], nextCursor=str(i)) for i in range(10)],
])
def test_malformed_or_partial_is_unknown(pages):
    with pytest.raises(ValueError): shells._count(Client(pages), THREAD)


@pytest.mark.parametrize('data,cursor', [([], None), (['foreign'], None), ([THREAD, 'foreign'], None), ([THREAD], 'partial')])
def test_foreign_or_incomplete_loaded_thread_refuses(data, cursor):
    with pytest.raises(ValueError):
        shells._count(Client([], loaded=dict(data=data, nextCursor=cursor)), THREAD)


def test_binding_generation_changed_after_read_is_unknown(monkeypatch):
    bindings = iter([dict(pid=1, endpoint='/tmp/socket', thread=THREAD), dict(pid=2, endpoint='/tmp/socket', thread=THREAD)])
    monkeypatch.setattr(shells, '_binding', lambda *a: next(bindings))
    monkeypatch.setattr(shells, '_Socket', lambda *a: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(shells, '_count', lambda *a: 0)
    assert shells.count('worker', '/tmp/root') is None


@pytest.mark.parametrize('error', [TimeoutError, OSError, ValueError, KeyError, TypeError])
def test_read_failure_never_defaults_zero(monkeypatch, error):
    monkeypatch.setattr(shells, '_binding', lambda *a: (_ for _ in ()).throw(error()))
    assert shells.count('worker', '/tmp/root') is None


@pytest.mark.parametrize('value,clear', [(0, True), (1, False), (None, False), (True, False), (-1, False)])
def test_codex_gate_requires_typed_native_zero(monkeypatch, value, clear):
    seen = []
    monkeypatch.setattr(shells, 'count', lambda agent, root: seen.append((agent, root)) or value)
    result = notify.unattended_shell_block('› ', 'codex', agent='worker', root='/tmp/root')
    assert (result == '') is clear
    assert seen == [('worker', '/tmp/root')]


def test_ui_positive_and_waiting_terminal_refuse_without_rpc(monkeypatch):
    monkeypatch.setattr(shells, 'count', lambda *a: pytest.fail('unneeded RPC'))
    assert '2 background' in notify.unattended_shell_block('2 shells still running', 'codex')
    assert 'still running' in notify.unattended_shell_block('Waiting for background terminal', 'codex')
    assert notify.unattended_shell_block('❯ ', 'claude') == ''


def test_pane_rechecked_after_native_zero(monkeypatch):
    screens = iter(['idle', 'busy'])
    panes = SimpleNamespace(exists=lambda *a: True, capture=lambda *a, **k: next(screens))
    runtime = SimpleNamespace(shows_ready_ui=lambda *a: True)
    monkeypatch.setattr(cli.harness_mod, 'name_for', lambda *a: 'codex')
    monkeypatch.setattr(cli.triage_mod, 'work_state', lambda screen, *a, **k: cli.triage_mod.IDLE if screen == 'idle' else 'busy')
    monkeypatch.setattr(cli, '_cycle_input_empty', lambda *a: True)
    monkeypatch.setattr(cli, 'asks_a_question', lambda *a: False)
    monkeypatch.setattr(cli, 'auth_expired', lambda *a: False)
    monkeypatch.setattr(cli, 'limit_reached', lambda *a: False)
    monkeypatch.setattr(shells, 'count', lambda *a: 0)
    assert 'not idle' in cli._automatic_cycle_refusal(SimpleNamespace(name='worker'), 'pane', panes, runtime, '/tmp/root')


def test_autocycler_passes_card_scope(monkeypatch, tmp_path):
    from shantytown.protocols import Agent
    card = Agent(name='worker', role='worker', pane='pane')
    seen = []
    monkeypatch.setattr(shells, 'count', lambda agent, root: seen.append((agent, root)) or 0)
    auto = notify.AutoCycler(tmp_path, SimpleNamespace(capture=lambda *a, **k: '› '), anchor=lambda *a: '', comments=lambda *a: [], requests=None, push=None, harness=lambda *a: 'codex')
    auto._agents = [card]
    assert auto._shell_block('worker') == ''
    assert seen == [('worker', tmp_path)]


def test_duplicate_json_fields_refused():
    with pytest.raises(ValueError): shells._decode('{"data":[1],"data":[]}')


def exact(sock, size):
    data = b''
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk: raise EOFError()
        data += chunk
    return data


@pytest.mark.parametrize('rows', [[], [terminal('42')]])
def test_actual_unix_websocket_wire(tmp_path, rows):
    path = str(tmp_path / 'rpc')
    listener = socket.socket(socket.AF_UNIX); listener.bind(path); listener.listen()
    errors = []
    def serve():
        try:
            with listener.accept()[0] as peer:
                head = b''
                while not head.endswith(b'\r\n\r\n'): head += exact(peer, 1)
                key = next(line.split(b':', 1)[1].strip() for line in head.split(b'\r\n') if line.startswith(b'Sec-WebSocket-Key:'))
                accept = base64.b64encode(hashlib.sha1(key + b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
                peer.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
                for _ in range(5):
                    first, second = exact(peer, 2); size = second & 127
                    if size == 126: size = struct.unpack('!H', exact(peer, 2))[0]
                    mask = exact(peer, 4); body = exact(peer, size)
                    request = json.loads(bytes(c ^ mask[i % 4] for i, c in enumerate(body)))
                    if 'id' not in request: continue
                    method = request['method']
                    result = {} if method == 'initialize' else dict(data=[THREAD] if method == 'thread/loaded/list' else rows, nextCursor=None)
                    data = json.dumps(dict(id=request['id'], result=result)).encode()
                    header = bytes([129, len(data)]) if len(data) < 126 else bytes([129, 126]) + struct.pack('!H', len(data))
                    peer.sendall(header + data)
        except BaseException as error: errors.append(error)
        finally: listener.close()
    worker = threading.Thread(target=serve, daemon=True); worker.start()
    client = shells._Socket(path, os.getpid(), time.monotonic() + 2)
    try: assert shells._count(client, THREAD) == len(rows)
    finally: client.close(); worker.join(2)
    assert not worker.is_alive() and not errors


@pytest.fixture
def binding_fixture(tmp_path):
    agent = 'worker'; runtime = tmp_path / 'runtime'; home = runtime / 'shantytown' / 'codex' / agent
    (home / 'app-server-daemon').mkdir(parents=True)
    (home / 'app-server-daemon' / 'daemon.pid').write_text(json.dumps(dict(pid=42)))
    proc = tmp_path / 'proc'; entry = proc / '42'; (entry / 'fd').mkdir(parents=True)
    (proc / 'net').mkdir()
    (entry / 'environ').write_bytes(b'SHANTY_AGENT=worker\0CODEX_HOME=' + os.fsencode(home) + b'\0')
    (entry / 'cmdline').write_bytes(b'codex\0app-server\0--remote-control\0--listen\0unix://\0')
    (entry / 'stat').write_text('42 (codex) S ' + '0 ' * 18 + '123\n')
    (entry / 'fd' / '3').symlink_to('socket:[1234]')
    listener = socket.socket(socket.AF_UNIX); endpoint = tmp_path / 'rpc'; listener.bind(str(endpoint))
    (proc / 'net' / 'unix').write_text('header\n0: 2 0 00010000 0001 01 1234 ' + str(endpoint) + '\n')
    root = tmp_path / 'root'; (root / 'context_budget').mkdir(parents=True)
    (home / 'sessions').mkdir(); transcript = home / 'sessions' / 'rollout.jsonl'
    transcript.write_text(json.dumps(dict(type='session_meta', payload=dict(id=THREAD))) + '\n')
    context = root / 'context_budget' / 'worker.json'
    context.write_text(json.dumps(dict(payload=dict(session_id=THREAD, transcript_path=str(transcript)))))
    yield dict(root=root, runtime=runtime, home=home, proc=proc, entry=entry, transcript=transcript, context=context)
    listener.close()


def binding(data):
    return shells._binding('worker', data['root'], runtime_dir=data['runtime'], proc=data['proc'])


def test_binding_positive_exact_card_daemon_and_session(binding_fixture):
    value = binding(binding_fixture)
    assert value['pid'] == 42 and value['start'] == '123' and value['thread'] == THREAD


@pytest.mark.parametrize('fault', ['foreign-agent', 'foreign-home', 'wrong-process', 'missing-listener', 'two-listeners', 'zombie', 'missing-context', 'foreign-transcript', 'wrong-session', 'large-header', 'duplicate-pid', 'boolean-pid'])
def test_binding_faults_are_not_runtime_zero(binding_fixture, fault):
    d = binding_fixture
    if fault == 'foreign-agent': (d['entry'] / 'environ').write_bytes(b'SHANTY_AGENT=other\0')
    elif fault == 'foreign-home': (d['entry'] / 'environ').write_bytes(b'SHANTY_AGENT=worker\0CODEX_HOME=/foreign\0')
    elif fault == 'wrong-process': (d['entry'] / 'cmdline').write_bytes(b'python\0')
    elif fault == 'missing-listener': (d['entry'] / 'fd' / '3').unlink()
    elif fault == 'two-listeners':
        (d['entry'] / 'fd' / '4').symlink_to('socket:[5678]')
        with (d['proc'] / 'net' / 'unix').open('a') as fh: fh.write('0: 2 0 00010000 0001 01 5678 /other\n')
    elif fault == 'zombie': (d['entry'] / 'stat').write_text('42 (codex) Z ' + '0 ' * 18 + '123\n')
    elif fault == 'missing-context': d['context'].unlink()
    elif fault == 'foreign-transcript':
        d['context'].write_text(json.dumps(dict(payload=dict(session_id=THREAD, transcript_path='/foreign/rollout'))))
    elif fault == 'wrong-session': d['transcript'].write_text(json.dumps(dict(type='session_meta', payload=dict(id='other'))) + '\n')
    elif fault == 'large-header': d['transcript'].write_bytes(b'x' * 65537)
    elif fault == 'duplicate-pid': (d['home'] / 'app-server-daemon' / 'daemon.pid').write_text('{"pid":42,"pid":1}')
    elif fault == 'boolean-pid': (d['home'] / 'app-server-daemon' / 'daemon.pid').write_text('{"pid":true}')
    with pytest.raises((OSError, ValueError, KeyError)): binding(d)


def test_non_finite_json_is_not_an_empty_result():
    with pytest.raises(ValueError): shells._decode('{"data":[],"extra":NaN}')


def test_codex_ui_zero_without_native_scope_is_unknown():
    assert 'zero is not visible' in notify.unattended_shell_block('0 shells still running', 'codex')
