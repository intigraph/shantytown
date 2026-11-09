"""Opt-in roster display protocol v2. Version1 peers and all decisions stay live."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

from . import crew_display_cache as cache


def validate_rows(value, host):
    if (not isinstance(value, dict) or value.get('version') != 1
            or value.get('scope') != 'local' or value.get('complete') is not True
            or value.get('host') != host or not isinstance(value.get('agents'), list)):
        raise ValueError('incomplete local display observation')
    names = set()
    for row in value['agents']:
        if (not isinstance(row, dict) or type(row.get('live')) is not bool
                or any(not isinstance(row.get(k), str) for k in
                       ('name', 'role', 'state', 'work', 'posture', 'harness',
                        'settings', 'tree', 'pane'))
                or not row['name'] or row['name'] in names):
            raise ValueError('invalid display row')
        names.add(row['name'])


def identity(a, host):
    """Include source, projected cards/config and all explicit read scopes."""
    from .cli import _backend, _registry_choice
    root = Path(a.root).resolve()
    source = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(source.glob('*.py')):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    for path in [root / 'shantytown.toml', *sorted((root / 'crew').glob('*.json'))]:
        digest.update(str(path).encode())
        if path.exists():
            digest.update(path.read_bytes())
    scopes = {key: value for key, value in os.environ.items()
              if key in ('SHANTY_BACKEND', 'SHANTY_REGISTRY', 'SEEDS_QUIPU_URL', 'SEEDS_GRAPH',
                         'QUIPU_SERVER', 'SHANTY_BR_REPO', 'SHANTY_BEADS_REPO',
                         'SHANTY_SD_QUIPU', 'SHANTY_SD_STORE', 'SHANTY_SD_PREFIX')}
    descriptor = [2, str(root), host, _backend(a),
                  _registry_choice(a), getattr(a, 'repo', None), scopes,
                  digest.hexdigest()]
    return hashlib.sha256(json.dumps(descriptor, sort_keys=True, default=str).encode()).hexdigest()


def _producer_code():
    # Linux is the deployed crew host contract. The producer and any tools it
    # starts die together when the requesting UI/SSH reader disappears.
    return (
        'import ctypes,os,signal,sys; '
        'signal.signal(signal.SIGTERM, lambda *_: os.killpg(os.getpgrp(),signal.SIGKILL)); '
        'libc=ctypes.CDLL(None); '
        'ok=libc.prctl(1,signal.SIGTERM,0,0,0)==0; '
        f'parent=os.getppid()=={os.getpid()}; '
        'sys.exit(3) if not ok else None; '
        'os.killpg(os.getpgrp(),signal.SIGKILL) if not parent else None; '
        'from shantytown.cli import main; sys.exit(main())')


def build_live(a):
    # A bounded child avoids unbounded multi-query refreshes and captures only
    # canonical local rows. No peers or display flag can recurse into this call.
    argv = [sys.executable, '-c',
            _producer_code(),
            '--root', str(a.root)]
    for name in ('backend', 'registry', 'repo'):
        if value := getattr(a, name, None):
            argv.extend(['--' + name, str(value)])
    argv.extend(['crew', '--json', '--local', '--no-priority-advice'])
    try:
        with subprocess.Popen(argv, cwd=Path(__file__).parent.parent,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, start_new_session=True) as child:
            try:
                stdout, _stderr = child.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate()
                raise ValueError('display producer deadline') from None
    except OSError:
        raise ValueError('display producer failed') from None
    if child.returncode or len(stdout.encode()) > cache.MAX_BYTES:
        raise ValueError('display producer refused or oversized')
    return json.loads(stdout)


def local_snapshot(a):
    from .deployment import local_host
    host = local_host(a.root) or 'local'
    value = cache.read(identity(a, host), lambda: build_live(a),
                       validate=lambda payload: validate_rows(payload, host))
    age = time.monotonic() - value['started']
    if not 0 <= age < cache.TTL:
        raise ValueError('display observation expired')
    return dict(version=2, purpose='display', decision_eligible=False,
                scope='local', host=host, complete=True, age_seconds=age,
                ttl_seconds=cache.TTL, sampled_at=value['sampled_at'],
                agents=value['payload']['agents'], errors=[], _received_at=time.monotonic())


def read_peer(peer):
    command = ('PATH="$HOME/.local/bin:$PATH" st --registry files --backend files --root '
               + shlex.quote(peer.root) + ' crew --json --local --display-snapshot')
    started = time.monotonic()
    try:
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                                 '--', peer.ssh, command], capture_output=True,
                                text=True, timeout=20)
        if result.returncode or len(result.stdout.encode()) > cache.MAX_BYTES:
            raise ValueError('display peer refused or oversized')
        value = json.loads(result.stdout)
        age = value.get('age_seconds')
        if (value.get('version') != 2 or value.get('purpose') != 'display'
                or value.get('decision_eligible') is not False
                or value.get('ttl_seconds') != cache.TTL
                or type(age) not in (float, int)
                or not 0 <= age + time.monotonic() - started < cache.TTL):
            raise ValueError('invalid or expired display peer')
        validate_rows(dict(value, version=1), peer.name)
        value['age_seconds'] = age + time.monotonic() - started
        if value['age_seconds'] >= cache.TTL:
            raise ValueError('display peer expired')
        value['_received_at'] = time.monotonic()
        return value
    except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired):
        return dict(version=2, purpose='display', decision_eligible=False,
                    scope='local', host=peer.name, complete=False, agents=[],
                    errors=[peer.name + ': display snapshot UNKNOWN'])


def command(a):
    from . import config, triage
    if (getattr(a, 'json', False) and getattr(a, 'count', False)) or any(getattr(a, name, False) for name in
           ('governor', 'pane_state', 'check_alert_keepers', 'trees')):
        print('display snapshot cannot be combined with decision/census options', file=sys.stderr)
        return 2
    try:
        cfg, error = config.load_or_default(Path(a.root))
        if error:
            raise ValueError('display configuration unknown')
        local = local_snapshot(a)
        peers = []
        if not getattr(a, 'local', False) and cfg.host_peers:
            with ThreadPoolExecutor(max_workers=min(16, len(cfg.host_peers))) as pool:
                peers = list(pool.map(read_peer, sorted(cfg.host_peers.values(), key=lambda p: p.name)))
        snapshots = [local, *peers]
        for snap in snapshots:
            received = snap.pop('_received_at', None)
            if received is not None:
                snap['age_seconds'] += time.monotonic() - received
                if not 0 <= snap['age_seconds'] < cache.TTL:
                    snap.update(complete=False, agents=[], errors=[snap['host'] + ': display expired'])
        errors = [e for snap in snapshots for e in snap['errors']]
        value = dict(version=2, purpose='display', decision_eligible=False,
                     scope='local' if getattr(a, 'local', False) else 'fleet',
                     complete=not errors, snapshots=snapshots, errors=errors)
        # Local peer protocol is deliberately separate from the fleet envelope.
        if getattr(a, 'json', False):
            print(json.dumps(local if getattr(a, 'local', False) else value))
        elif errors:
            print('UNKNOWN display snapshot')
        elif getattr(a, 'count', False):
            rows = [row for snap in snapshots for row in snap['agents']]
            busy = sum(row['work'] == triage.BUSY for row in rows)
            total = sum(row['work'] in (triage.BUSY, triage.IDLE) for row in rows)
            print(f'{busy}/{total} (display; at most {cache.TTL}s old)')
        else:
            print('DISPLAY ONLY — observations at most 15s old; decisions require live reads')
            for snap in snapshots:
                for row in snap['agents']:
                    print(f"{snap['host']} {row['name']} {row['state']} {row['work']}")
        return 3 if errors else 0
    except (OSError, ValueError, TypeError, KeyError, SystemExit):
        if getattr(a, 'json', False):
            print(json.dumps(dict(version=2, purpose='display', decision_eligible=False,
                                  scope='local' if getattr(a, 'local', False) else 'fleet',
                                  complete=False, agents=[], errors=['display snapshot UNKNOWN'])))
        else:
            print('UNKNOWN display snapshot')
        return 3
