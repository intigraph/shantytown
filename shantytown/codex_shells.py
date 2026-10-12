"""Fresh, read-only terminal counts from a proven per-card Codex daemon.

Missing identity, an incomplete response or a changed generation is UNKNOWN.
No thread is started/resumed, no terminal is cleaned, and no token is copied.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import time
import uuid

MAX_BYTES = 1024 * 1024


def _decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON field')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite JSON")))


def _regular(path):
    # A broken identity file must not block the lifecycle lock on a FIFO.
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('identity is not an owned regular file')
        return os.fdopen(descriptor, 'rb')
    except BaseException:
        os.close(descriptor)
        raise


def _json(path, cap=65536):
    with _regular(path) as fh:
        raw = fh.read(cap + 1)
    if len(raw) > cap:
        raise ValueError('identity size cap')
    value = _decode(raw)
    if not isinstance(value, dict):
        raise ValueError('identity is not an object')
    return value, hashlib.sha256(raw).hexdigest()


def _binding(agent, root, *, runtime_dir=None, proc=Path('/proc')):
    if root is None or not re.fullmatch(r'[A-Za-z0-9_-]+', agent):
        raise ValueError('missing card binding')
    home = Path(runtime_dir or os.environ.get('XDG_RUNTIME_DIR', Path.home() / '.cache')) / 'shantytown' / 'codex' / agent
    record, generation = _json(home / 'app-server-daemon' / 'daemon.pid')
    pid = record.get('pid')
    if type(pid) is not int or pid <= 0:
        raise ValueError('missing daemon PID')
    entry = proc / str(pid)
    env = dict(x.split(b'=', 1) for x in (entry / 'environ').read_bytes().split(b'\0') if b'=' in x)
    if env.get(b'SHANTY_AGENT') != agent.encode() or env.get(b'CODEX_HOME') != os.fsencode(home):
        raise ValueError('foreign daemon')
    cmd = (entry / 'cmdline').read_bytes().split(b'\0')
    if b'app-server' not in cmd or b'--remote-control' not in cmd or b'--listen' not in cmd or not cmd[cmd.index(b'--listen') + 1].startswith(b'unix://'):
        raise ValueError('not a control daemon')
    raw = (entry / 'stat').read_text()
    fields = raw[raw.rfind(')') + 2:].split()
    if len(fields) < 20 or fields[0] == 'Z' or not fields[19].isdigit():
        raise ValueError('daemon generation unreadable')
    start = fields[19]
    descriptors = list((entry / 'fd').iterdir())
    if len(descriptors) > 4096:
        raise ValueError('descriptor cap')
    inodes = set()
    for fd in descriptors:
        try:
            link = str(fd.readlink())
        except FileNotFoundError:
            continue
        if link.startswith('socket:[') and link.endswith(']'):
            inodes.add(link[8:-1])
    with (proc / 'net' / 'unix').open() as fh:
        table = fh.read(MAX_BYTES + 1)
    if len(table) > MAX_BYTES:
        raise ValueError('socket table cap')
    paths = set()
    for line in table.splitlines()[1:]:
        row = line.split(maxsplit=7)
        if len(row) == 8 and row[6] in inodes and int(row[3], 16) & 0x10000 and row[4] == '0001':
            paths.add(row[7])
    if len(paths) != 1:
        raise ValueError('ambiguous listener')
    endpoint = Path(next(iter(paths)))
    st = endpoint.stat()
    if not endpoint.is_absolute() or not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid():
        raise ValueError('foreign socket')
    context, context_generation = _json(Path(root) / 'context_budget' / f'{agent}.json')
    payload = context.get('payload')
    if not isinstance(payload, dict):
        raise ValueError('missing session identity')
    thread = payload.get('session_id')
    if not isinstance(thread, str) or str(uuid.UUID(thread)) != thread:
        raise ValueError('invalid session ID')
    transcript = Path(payload['transcript_path']).resolve()
    if not transcript.resolve().is_relative_to((home / 'sessions').resolve()):
        raise ValueError('foreign transcript')
    with _regular(transcript) as fh:
        first = fh.readline(65537)
    if len(first) > 65536:
        raise ValueError('session header cap')
    header = _decode(first)
    if not isinstance(header, dict) or not isinstance(header.get('payload'), dict) or header.get('type') != 'session_meta' or header['payload'].get('id') != thread:
        raise ValueError('session header mismatch')
    return dict(pid=pid, start=start, endpoint=str(endpoint), thread=thread,
                generation=generation, context_generation=context_generation)


class _Socket:
    def __init__(self, endpoint, pid, deadline):
        self.deadline = deadline
        self.buffer = b''
        self.socket = socket.socket(socket.AF_UNIX)
        try:
            self._timeout()
            self.socket.connect(endpoint)
            if not hasattr(socket, 'SO_PEERCRED'):
                raise ValueError('peer PID unavailable')
            peer, uid, _ = struct.unpack('3i', self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if peer != pid or uid != os.getuid():
                raise ValueError('foreign RPC peer')
            key = base64.b64encode(os.urandom(16)).decode()
            self.socket.sendall((f'GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n'
                                 f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n'
                                 'Sec-WebSocket-Version: 13\r\n\r\n').encode())
            while b'\r\n\r\n' not in self.buffer:
                self._receive(4096)
                if len(self.buffer) > 16384:
                    raise ValueError('handshake cap')
            head, self.buffer = self.buffer.split(b'\r\n\r\n', 1)
            lines = head.decode('ascii').split('\r\n')
            headers = {k.lower(): v.strip() for line in lines[1:] if ':' in line for k, v in [line.split(':', 1)]}
            expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            if lines[0] != 'HTTP/1.1 101 Switching Protocols' or headers.get('sec-websocket-accept') != expected or headers.get('upgrade', '').lower() != 'websocket' or 'upgrade' not in {token.strip().lower() for token in headers.get('connection', '').split(',')}:
                raise ValueError('invalid upgrade')
        except BaseException:
            self.socket.close()
            raise

    def close(self):
        self.socket.close()

    def _timeout(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('RPC deadline')
        self.socket.settimeout(remaining)

    def _receive(self, size):
        self._timeout()
        data = self.socket.recv(size)
        if not data:
            raise ValueError('RPC EOF')
        self.buffer += data

    def _take(self, size):
        while len(self.buffer) < size:
            self._receive(size - len(self.buffer))
        out, self.buffer = self.buffer[:size], self.buffer[size:]
        return out

    def send(self, value, opcode=1):
        data = json.dumps(value).encode() if opcode == 1 else value
        size = len(data)
        if size > MAX_BYTES:
            raise ValueError('request cap')
        mask = os.urandom(4)
        if size < 126:
            header = bytes([128 | opcode, 128 | size])
        elif size < 65536:
            header = bytes([128 | opcode, 128 | 126]) + struct.pack('!H', size)
        else:
            header = bytes([128 | opcode, 128 | 127]) + struct.pack('!Q', size)
        self._timeout()
        self.socket.sendall(header + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def request(self, number, method, params):
        self.send(dict(id=number, method=method, params=params))
        total = 0
        for _ in range(100):
            first, second = self._take(2)
            size = second & 127
            if size == 126:
                size = struct.unpack('!H', self._take(2))[0]
            elif size == 127:
                size = struct.unpack('!Q', self._take(8))[0]
            total += size
            if total > MAX_BYTES or second & 128 or first & 0x70 or not first & 128:
                raise ValueError('unsupported frame')
            body = self._take(size)
            opcode = first & 15
            if opcode == 9 and size <= 125:
                self.send(body, 10)
                continue
            if opcode != 1:
                raise ValueError('RPC closed or non-text frame')
            result = _decode(body)
            if not isinstance(result, dict):
                raise ValueError('non-object RPC')
            if type(result.get('id')) is int and result['id'] == number:
                if 'error' in result or not isinstance(result.get('result'), dict):
                    raise ValueError('RPC refused')
                return result['result']
        raise ValueError('RPC message cap')


def _loaded(client, number, thread):
    result = client.request(number, 'thread/loaded/list', dict(limit=100))
    if result.get('data') != [thread] or 'nextCursor' not in result or result['nextCursor'] is not None:
        raise ValueError('current thread not uniquely loaded')


def _count(client, thread):
    client.request(1, 'initialize', dict(clientInfo=dict(name='shantytown-runtime-count', title='Read-only terminal count', version='1'), capabilities=dict(experimentalApi=True)))
    client.send(dict(method='initialized', params={}))
    _loaded(client, 2, thread)
    seen, cursors = set(), set()
    cursor = None
    for page in range(10):
        result = client.request(3 + page, 'thread/backgroundTerminals/list', dict(threadId=thread, limit=100, cursor=cursor))
        rows = result.get('data')
        if not isinstance(rows, list) or 'nextCursor' not in result:
            raise ValueError('incomplete terminal list')
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('itemId'), str) or not row['itemId'] or not isinstance(row.get('command'), str) or not isinstance(row.get('cwd'), str):
                raise ValueError('malformed terminal row')
            process = row.get('processId') if isinstance(row, dict) else None
            if not isinstance(process, str) or not process or process.strip() != process or len(process) > 256 or not process.isascii() or any(ord(c) < 32 for c in process) or process in seen:
                raise ValueError('ambiguous process ID')
            seen.add(process)
        if len(seen) >= 1000:
            raise ValueError('terminal cap')
        cursor = result['nextCursor']
        if cursor is None:
            _loaded(client, 20, thread)
            return len(seen)
        if not isinstance(cursor, str) or not cursor or cursor in cursors or len(cursor) > 4096:
            raise ValueError('invalid pagination')
        cursors.add(cursor)
    raise ValueError('pagination cap')


def count(agent, root, *, timeout=3.0):
    """Return a fresh complete count, or None. Never cache an empty result."""
    if not hasattr(socket, 'SO_PEERCRED') or not hasattr(os, 'O_NOFOLLOW'):
        return None
    client = None
    try:
        before = _binding(agent, root)
        client = _Socket(before['endpoint'], before['pid'], time.monotonic() + timeout)
        result = _count(client, before['thread'])
        if _binding(agent, root) != before:
            return None
        return result
    except (OSError, ValueError, TypeError, KeyError, IndexError, struct.error):
        return None
    finally:
        if client is not None:
            client.close()
