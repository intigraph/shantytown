"""Account observations merged across hosts without inventing a fresh timestamp."""
from __future__ import annotations

import math
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from contextlib import contextmanager
import json
import hashlib
import os
from pathlib import Path
import select
import shlex
import subprocess
import time
import tempfile

from . import governor as gov
from . import governor_balance as balance_mod
from .governor import GovernorError, Reading

VERSION = 1
# The same host-clock allowance applies in either direction and to cached evidence.
CLOCK_SKEW_SECONDS = 60
# A remembered census older than this is advisory: reported, never counted and
# never a source of borrowed policy, so it cannot hold this host's launches.
# `[host] peer_census_max_age` (seconds) overrides it.
PEER_CENSUS_MAX_AGE = 6 * 60 * 60
PEER_COUNT_MAX_AGE = PEER_CENSUS_MAX_AGE  # old name, kept for importers


class PeerUnreachable(str):
    """Transport failure, distinct from a reachable peer's invalid census."""


def _peer_cache(root, peer):
    # Changing the endpoint must not borrow another host's occupancy evidence.
    key = hashlib.sha256(json.dumps([peer.name, peer.ssh, peer.root]).encode()).hexdigest()
    return Path(root) / 'governor' / 'peers' / (key + '.json')


def _save_peer(path, snapshot, error):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
            temporary = handle.name
            json.dump(dict(snapshot=snapshot, error=str(error)), handle)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


class AdmissionUnavailable(GovernorError):
    pass


@dataclass(frozen=True)
class Admission:
    """Which lock serialized this launch, and whether the owner was skipped.

    `lock_host` is the host whose `governor/admission.lock` is held (this host
    unless the configured owner's lock was taken over SSH). `unreachable` names
    a configured owner that could not be reached, so the census-to-launch
    section ran under this host's own lock instead (degraded admission).
    """
    lock_host: str | None = None
    owner: str | None = None
    unreachable: str | None = None


@contextmanager
def _local_lock(root):
    import fcntl
    path = Path(root) / 'governor' / 'admission.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        deadline = time.monotonic() + 10
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise AdmissionUnavailable('account admission busy; retry after the current launch')
                time.sleep(.05)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


_REMOTE_LOCK = '''import fcntl, pathlib, sys, time
p = pathlib.Path(sys.argv[1]) / 'governor' / 'admission.lock'
p.parent.mkdir(parents=True, exist_ok=True)
with p.open('a') as f:
    deadline = time.monotonic() + 10
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                sys.exit(2)
            time.sleep(.05)
    print('locked', flush=True)
    sys.stdin.buffer.read(1)
'''
REMOTE_LOCK_BUSY = 2
# How long this host waits for the owner's helper to print `locked`.
REMOTE_LOCK_READY_S = 16
# After that, how long a helper still waiting on the owner's lock may take to
# reach its own 10s deadline and exit BUSY. SSH connect+auth time is spent
# before the helper's clock starts, so the two deadlines are not aligned; a
# helper that is merely waiting must not be mistaken for an unreachable owner.
REMOTE_LOCK_BUSY_GRACE_S = 12
_LOCK_LINE_MAX = 64 * 1024


def _await_locked(process, timeout):
    """True once the helper prints a `locked` line, tolerating shell noise
    (login banners, rc output) before it. False on EOF, timeout or a flood."""
    fd = process.stdout.fileno()
    deadline = time.monotonic() + timeout
    pending = b''
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return False
        ready, _, _ = select.select([fd], [], [], left)
        if not ready:
            return False
        chunk = os.read(fd, 4096)
        if not chunk:
            return False
        lines = (pending + chunk).split(b'\n')
        pending = lines.pop()
        if any(line.rstrip(b'\r') == b'locked' for line in lines):
            return process.poll() is None
        if len(pending) > _LOCK_LINE_MAX:
            return False


@contextmanager
def admission_lock(root, host, peers, *, owner=None, local_required=False):
    """Serialize census-to-launch, preferring the configured owner's lock.

    With a reachable `[host] admission_owner`, every host serializes on that
    one lock and reads a fresh census under it, exactly as before. When the
    owner cannot be reached, or none is configured, this host takes its OWN
    lock and admits against what it can see: fresh censuses of reachable peers
    and the last census of every unreachable one (FleetGovernor). An
    unreachable host is never by itself a refusal; `st` must work on any host
    without depending on another host running `st`.

    A BUSY owner (reachable, lock held by another launch) still refuses: that
    is real contention, not an outage. Yields an `Admission`.
    This is coordination for a trusted fleet, not a consensus service.
    """
    if not peers:
        if owner is not None and owner != host:
            raise AdmissionUnavailable('account admission authority is not a declared host')
        if not local_required:
            yield Admission(owner=owner)
            return
        with _local_lock(root):
            yield Admission(lock_host=host or 'local', owner=host or 'local')
        return
    if not host or host in peers:
        raise AdmissionUnavailable('account admission needs a unique local host name')
    if owner is not None and owner not in {host, *peers}:
        raise AdmissionUnavailable('account admission authority is not a declared host')
    if owner is None or owner == host:
        with _local_lock(root):
            yield Admission(lock_host=host, owner=owner)
        return
    peer = peers[owner]
    command = 'python3 -u -c ' + shlex.quote(_REMOTE_LOCK) + ' ' + shlex.quote(peer.root)
    process = None
    try:
        process = subprocess.Popen(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
             '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
             '--', peer.ssh, command], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        process = None
    locked = process is not None and _await_locked(process, REMOTE_LOCK_READY_S)
    if locked:
        try:
            yield Admission(lock_host=owner, owner=owner)
        finally:
            _release(process)
        return
    busy = False
    if process is not None:
        # Let a helper that is still waiting on the owner's lock reach its own
        # deadline: exit BUSY means the owner is up and another launch holds it.
        _release(process, grace=REMOTE_LOCK_BUSY_GRACE_S)
        busy = process.returncode == REMOTE_LOCK_BUSY
    if busy:
        raise AdmissionUnavailable(f'account admission authority {owner} busy; '
                                   'retry after the current launch')
    # Transport failure, a hung connection, or no working lock helper on the
    # owner: the owner is out of reach. Degrade to this host's own lock.
    with _local_lock(root):
        yield Admission(lock_host=host, owner=owner, unreachable=owner)


def _release(process, grace=3):
    try:
        process.stdin.close()
    except OSError:
        pass
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    process.stdout.close()


def _age_text(seconds):
    if seconds is None:
        return 'unknown'
    seconds = max(0, int(seconds))
    for unit, size in (('d', 86400), ('h', 3600), ('m', 60)):
        if seconds >= size:
            return f'{seconds // size}{unit}'
    return f'{seconds}s'


def degraded_admission_line(admission, fleet):
    """ONE line naming every host admission could not see, or '' when none.

    Printed whenever a launch is admitted without a fresh census of every
    declared host, so a degraded admission is never silent.
    """
    estimates = dict(getattr(fleet, 'estimates', None) or {})
    skipped = getattr(admission, 'unreachable', None)
    if not estimates and not skipped:
        return ''
    down = sorted(set(estimates) | ({skipped} if skipped else set()))
    against = []
    for name in down:
        estimate = estimates.get(name)
        if estimate is None:
            against.append(f'a fresh census of {name}')
        elif estimate['age'] is None:
            against.append(f'no usable census of {name} (counted 0 live)')
        elif estimate.get('advisory'):
            against.append(f"{name}'s last census (age {_age_text(estimate['age'])}, "
                           'advisory, counted 0)')
        else:
            against.append(f"{name}'s last census (age {_age_text(estimate['age'])}, "
                           f"{estimate['live']} live)")
    lock_host = getattr(admission, 'lock_host', None)
    remote_lock = bool(lock_host) and not skipped and lock_host != getattr(fleet, 'local', None)
    where = f"under {lock_host}'s lock" if remote_lock else 'locally'
    return f"admission: {', '.join(down)} unreachable; admitted {where} against {', '.join(against)}"


# Policy is portable; reader coordinates and credentials emphatically are not.
POLICY_FIELDS = ('window', 'on_signal_lost', 'relax_margin', 'max_age_seconds',
                 'max_agents', 'delegation_reserve_pct', 'exempt', 'limit_id',
                 'admit_class', 'class_exempt')


def policy_wire(policy):
    data = {key: getattr(policy, key) for key in POLICY_FIELDS}
    data.update(tier=[asdict(t) for t in policy.tiers],
                burndown=[asdict(b) for b in policy.burndowns],
                # An empty `curve` is "no envelope" and must not travel as one:
                # the parser reads a present `curve` key as a declared envelope.
                pace=[{k: v for k, v in asdict(p).items()
                       if not (k == 'curve' and not v)} for p in policy.paces])
    # aegis-hnv7: carried ONLY when declared, so a fleet whose configs do not use
    # it keeps a byte-identical wire that an older peer's strict check accepts.
    if policy.optional_windows:
        data['optional_windows'] = list(policy.optional_windows)

    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if v is not None}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        return value
    return clean(data)


def observations(governor):
    """Read once, preserving failed probes without exporting transport secrets."""
    reader = governor.reader
    try:
        if hasattr(reader, 'read_all_detailed'):
            readings, error, fault = reader.read_all_detailed()
            if error and not readings:
                readings = {w: Reading(ok=False, error='local usage reader failed',
                                       fault=fault) for w in governor.policy.windows()}
        elif hasattr(reader, 'read_all'):
            readings = reader.read_all()
        else:
            readings = {governor.policy.window: reader.read()}
    except Exception:
        readings = {w: Reading(ok=False, error='local usage reader failed')
                    for w in governor.policy.windows()}
    def wire(r):
        data = asdict(replace(r, source='host-observation',
                              error='local usage reader failed' if r.error else ''))
        # aegis-hnv7: `offered` travels only when False (the server's stated
        # absence), so ordinary readings stay byte-identical for older peers.
        if data.get('offered', True) is True:
            data.pop('offered', None)
        return data
    return {w: wire(r) for w, r in readings.items()}


def snapshot(host, governors, agents, *, now=None, hosts=None, admission_owner=None):
    value = dict(version=VERSION, scope='local', host=host, complete=True,
                observed_at=time.time() if now is None else now, agents=agents,
                governors={name: dict(policy=policy_wire(g.policy),
                                      readings=observations(g),
                                      state=asdict(g.state.get() if g.state else gov.Engaged()))
                           for name, g in governors.items()})
    if hosts is not None:
        value['hosts'] = sorted(hosts)
    value['admission_owner'] = admission_owner or (host if not hosts or len(hosts) == 1 else None)
    return value


def _number(value, *, optional=False):
    if optional and value is None:
        return
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('invalid numeric observation')


def validate(value, host, *, now=None):
    clock = time.time() if now is None else now
    if (not isinstance(value, dict) or value.get('version') != VERSION
            or value.get('scope') != 'local' or value.get('host') != host
            or value.get('complete') is not True
            or not isinstance(value.get('agents'), list)
            or not isinstance(value.get('governors'), dict)):
        raise ValueError('incompatible or incomplete governor snapshot')
    _number(value.get('observed_at'))
    if not -CLOCK_SKEW_SECONDS <= clock - value['observed_at'] <= CLOCK_SKEW_SECONDS:
        raise ValueError('stale or future governor census')
    names = set()
    for row in value['agents']:
        if (not isinstance(row, dict) or type(row.get('live')) is not bool
                or not isinstance(row.get('name'), str) or not row['name']
                or row['name'] in names or row.get('host') != host
                or not isinstance(row.get('harness'), str) or not row['harness']):
            raise ValueError('invalid or duplicate governor agent row')
        names.add(row['name'])
    for name, entry in value['governors'].items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            raise ValueError('invalid governor lane')
        policy = entry.get('policy')
        if not isinstance(policy, dict) or set(policy) - set(POLICY_FIELDS) - {'tier', 'burndown', 'pace', 'optional_windows'}:
            raise ValueError('invalid portable policy')
        gov.parse(policy)
        readings = entry.get('readings')
        if not isinstance(readings, dict):
            raise ValueError('missing usage readings')
        for window, raw in readings.items():
            if not isinstance(window, str) or not isinstance(raw, dict):
                raise ValueError('invalid window observation')
            reading = Reading(**raw)
            for key in ('pct', 'at', 'cache_age', 'reset_at', 'probe_http_status'):
                _number(getattr(reading, key), optional=True)
            if (type(reading.ok) is not bool or type(reading.offered) is not bool
                    or not isinstance(reading.error, str)
                    or not isinstance(reading.source, str)
                    or reading.pct is not None and not 0 <= reading.pct <= 100
                    or reading.at is not None and reading.at > clock + CLOCK_SKEW_SECONDS):
                raise ValueError('invalid usage observation')
        state = entry.get('state')
        if not isinstance(state, dict) or not isinstance(state.get('by_window'), dict):
            raise ValueError('invalid governor hold')
        engaged = gov.Engaged(**state)
        _number(engaged.at, optional=True)
        _number(engaged.since)
        for held in engaged.by_window.values():
            if not isinstance(held, dict):
                raise ValueError('invalid window hold')
            for key in ('at', 'since', 'reset'):
                _number(held.get(key), optional=True)
    return value


def _ssh_transport_detail(stderr):
    """Retain a recognized final transport cause, never arbitrary remote output.

    stderr may contain credentials or remote command output. Match only the
    last nonempty line and emit fixed diagnostic text rather than echoing it.
    """
    lines = str(stderr or '').strip().splitlines()
    last = lines[-1].strip().lower() if lines else ''
    for needle, detail in (
        ('no route to host', 'No route to host'),
        ('network is unreachable', 'Network is unreachable'),
        ('connection refused', 'Connection refused'),
        ('connection timed out', 'Connection timed out'),
        ('operation timed out', 'Operation timed out'),
        ('could not resolve hostname', 'Could not resolve hostname'),
        ('host key verification failed', 'Host key verification failed'),
        ('permission denied', 'Permission denied'),
        ('connection reset', 'Connection reset'),
        ('connection closed', 'Connection closed'),
    ):
        if needle in last:
            return ': ' + detail
    return ''


def read_peer(peer):
    command = ('PATH="$HOME/.local/bin:$PATH" st --root '
               + shlex.quote(peer.root) + ' crew --governor --json --local')
    try:
        result = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '--',
             peer.ssh, command], capture_output=True, text=True, timeout=20)
        if result.returncode == 255:
            return None, PeerUnreachable(
                f'{peer.name} governor unreachable (SSH transport failed'
                f'{_ssh_transport_detail(result.stderr)})')
        if result.returncode:
            # The host answered but its `st` did not (missing, crashed, refused).
            # Another host's tooling must not be a dependency of this one: use
            # its last census exactly as for a transport failure. Never echo
            # remote stderr; it may carry credentials.
            return None, PeerUnreachable(
                f'{peer.name} governor unreachable (remote st exit {result.returncode})')
        if len(result.stdout) > 1024 * 1024:
            raise ValueError('governor snapshot exceeds 1 MiB')
        return validate(json.loads(result.stdout), peer.name), ''
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, PeerUnreachable(f'{peer.name} governor unreachable ({type(exc).__name__})')
    except (ValueError, TypeError, GovernorError) as exc:
        return None, f'{peer.name} governor unavailable ({type(exc).__name__}: {exc})'


def collect(peers):
    ordered = sorted(peers.values(), key=lambda p: p.name)
    if not ordered:
        return []
    with ThreadPoolExecutor(max_workers=min(16, len(ordered))) as pool:
        return list(pool.map(read_peer, ordered))


class MergedState:
    def __init__(self, states, destination, windows):
        self.destination = destination
        held = {}
        for window in windows:
            # The strictest remembered hold survives; either host may have seen
            # a crossing the other missed. Governor.evaluate still releases it
            # on the merged reading using the ordinary margin/rollover rules.
            state = max(states, key=lambda s: (s.hold(window)[0] or -1,
                                               s.hold(window)[1]))
            at, since = state.hold(window)
            held[window] = dict(at=at, since=since, reset=state.reset_of(window))
        self.engaged = gov.Engaged(by_window=held)

    def get(self):
        return self.engaged

    def set(self, value):
        self.engaged = value
        self.destination.set(value)


class FleetGovernor:
    """One invocation's account view, with explicit offline occupancy estimates.

    A peer that is UNREACHABLE (transport failure, or its `st` not answering)
    or that answers with an INVALID census is never by itself a refusal. Its
    last good census is counted only while younger than `census_max_age`
    (default PEER_CENSUS_MAX_AGE); an older, future-stamped, corrupt or missing
    census is ADVISORY: reported in `warnings`, counted as 0, and never a source
    of policy, so local launches answer to local capacity and the local
    governor alone. A REACHABLE peer with a valid census that disagrees
    (policy, membership, owner) still holds growth via `errors`.
    """
    def __init__(self, local, peers, root, *, peer_config=None, now=None,
                 census_max_age=None):
        self.local = local['host']
        clock = time.time() if now is None else now
        max_age = PEER_CENSUS_MAX_AGE if census_max_age is None else census_max_age
        self.warnings = []
        self.estimated_agents = []
        # peer name -> dict(age=seconds or None when no usable census, live=int)
        self.estimates = {}
        # one short phrase per degraded peer, for the single-line notice()
        self._degraded = []
        self._summarized = 0  # warnings the _degraded phrases already cover
        cached = []
        errors = []
        if peer_config:
            ordered = sorted(peer_config.values(), key=lambda p: p.name)
            if len(ordered) != len(peers):
                errors.append('peer census result count disagrees with declared membership')
            for peer, (snapshot, error) in zip(ordered, peers):
                path = _peer_cache(root, peer)
                if not error:
                    try:
                        _save_peer(path, snapshot, '')
                    except OSError:
                        self.warnings.append(f'{peer.name} governor cache could not be saved')
                    continue
                # Unreachable, or reachable with an unusable census (version
                # skew, clock skew, garbage). Neither may hold this host: fall
                # back to the last good census while it is fresh enough.
                state = ('unreachable' if isinstance(error, PeerUnreachable)
                         else 'census invalid')
                if not isinstance(error, PeerUnreachable):
                    self.warnings.append(error)
                    self._summarized += 1
                rows, age, advisory = [], None, False
                try:
                    record = json.loads(path.read_text())
                    if not isinstance(record, dict):
                        raise ValueError('invalid cached census record')
                    if record['error']:
                        raise ValueError('last reachable census was invalid')
                    prior = record['snapshot']
                    validate(prior, peer.name, now=prior['observed_at'])
                except FileNotFoundError:
                    detail = 'never seen; occupancy UNKNOWN, counted 0'
                    short = 'never seen'
                except (OSError, ValueError, TypeError, KeyError, GovernorError) as exc:
                    detail = f'cached census unusable ({exc}); occupancy UNKNOWN, counted 0'
                    short = 'no usable census'
                else:
                    age = clock - prior['observed_at']
                    advisory = age > max_age or age < -CLOCK_SKEW_SECONDS
                    if age > max_age:
                        detail = (f'cached census age {age:.0f}s exceeds '
                                  f'{max_age:.0f}s; advisory only, counted 0')
                        short = f'census {_age_text(age)} old, advisory'
                    elif age < -CLOCK_SKEW_SECONDS:
                        detail = 'cached census stamped in the future; advisory only, counted 0'
                        short = 'census future-stamped, advisory'
                    else:
                        cached.append(prior)
                        rows = prior['agents']
                        live = sum(r['live'] for r in rows)
                        detail = f'cached count age {max(0, age):.0f}s; {live} counted live'
                        short = f'{live} counted from {_age_text(age)}-old census'
                self.estimated_agents.extend(dict(row, estimated=True) for row in rows)
                self.estimates[peer.name] = dict(age=age, live=sum(r['live'] for r in rows))
                if advisory:
                    self.estimates[peer.name]['advisory'] = True
                self.warnings.append(f'{peer.name} {state}; {detail}')
                self._degraded.append(f'{peer.name} {state} ({short})')
                self._summarized += 1
        else:
            errors.extend(error for _, error in peers if error)
        self.snapshots = [local] + [s for s, error in peers if s is not None and not error]
        self.errors = errors
        # Agreement is demanded of hosts that ANSWERED. A remembered census is
        # history: its disagreement is reported but cannot hold this host.
        owner = local.get('admission_owner')
        for item in self.snapshots[1:]:
            if item.get('admission_owner') != owner:
                self.errors.append(f'{item["host"]} admission authority missing or disagrees; '
                                   'configure the same [host] admission_owner (or none) on every peer')
        for prior in cached:
            if prior.get('admission_owner') != owner:
                self.warnings.append(f'{prior["host"]} last census named a different admission authority')
        if 'hosts' in local:
            for item in self.snapshots[1:]:
                if item.get('hosts') != local['hosts']:
                    self.errors.append(f'{item["host"]} host membership disagrees; '
                                       'cannot establish one admission authority')
            for prior in cached:
                if prior.get('hosts') != local['hosts']:
                    self.warnings.append(f'{prior["host"]} last census declared different host membership')
        self.governors = {}
        self.policy_hosts = {}
        live_lanes = {name for s in self.snapshots for name in s['governors']}
        for prior in cached:
            for name, entry in prior['governors'].items():
                current = next((s['governors'][name] for s in self.snapshots
                                if name in s['governors']), None)
                if current and current['policy'] != entry['policy']:
                    self.warnings.append(f'{name} policy in {prior["host"]}\'s last census differs; '
                                         'admitting under the current policy')
        lanes = sorted(live_lanes | {name for s in cached for name in s['governors']})
        for name in lanes:
            entries = {s['host']: s['governors'][name] for s in self.snapshots
                       if name in s['governors']}
            borrowed = not entries
            if borrowed:
                # Only an unreachable peer declared this lane. Borrow its policy
                # so its cap still binds; its readings keep their original
                # timestamps and age into signal-lost like any other reading.
                entries = {s['host']: s['governors'][name] for s in cached
                           if name in s['governors']}
                self.warnings.append(f'{name} policy taken from the last census of '
                                     + ', '.join(sorted(entries)))
            host = min(entries)
            data = entries[host]['policy']
            if any(entry['policy'] != data for entry in entries.values()):
                if borrowed:
                    self.warnings.append(f'{name} policies in unreachable hosts\' last censuses '
                                         f'disagree; using {host}\'s')
                else:
                    self.errors.append(f'{name} governor policies disagree across hosts; growth held')
            policy = gov.parse(data)
            reader = FreshestReader({h: {w: Reading(**r) for w, r in e['readings'].items()}
                                     for h, e in entries.items()})
            states = [gov.Engaged(**e['state']) for e in entries.values()]
            destination = gov.FilesGovernorState(root, None if name == 'base' else name)
            state = MergedState(states, destination, policy.windows())
            self.governors[name] = gov.Governor(policy, reader, state, name=name)
            self.policy_hosts[name] = host

    @property
    def agents(self):
        return [row for snapshot in self.snapshots for row in snapshot['agents']] + self.estimated_agents

    def lane(self, harness):
        if harness in self.governors:
            return harness
        if len(self.governors) == 1 or harness == 'claude':
            return 'base'
        return harness

    def counts(self, local_agents=None):
        rows = [r for r in self.agents if local_agents is None or r['host'] != self.local]
        if local_agents is not None:
            rows += local_agents
        result = {name: 0 for name in self.governors}
        for row in rows:
            if row['live']:
                lane = self.lane(row.get('account') or row['harness'])
                result[lane] = result.get(lane, 0) + 1
        return result

    def notice(self):
        """At most ONE short line for per-command stderr; '' when all is well.

        The full list stays in `warnings` (`st crew --governor`, JSON)."""
        if not self.warnings:
            return ''
        parts = self._degraded or [self.warnings[0]]
        extra = len(self.warnings) - (self._summarized if self._degraded else 1)
        line = 'peers: ' + '; '.join(parts)
        if extra > 0:
            line += f'; +{extra} note{"s" if extra > 1 else ""}'
        return line + ' (st crew --governor)'

    def fallback(self):
        if not self.errors:
            return ''
        return ('; '.join(self.errors) + '; local/available usage fallback; '
                'peer occupancy or agreement UNKNOWN; new launches and dispatch held')

    def lane_paces(self, now=None, local_agents=None):
        """Each lane's seven_day pace, or the reason it has none (aegis-03cstj).

        seven_day and not five_hour, and that is forced rather than chosen: the codex
        limit publishes NO five-hour window at all -- `st crew --governor` prints
        `?/?/?` for it and always will -- so seven_day is the only window the two lanes
        have in common. A balance view on a window one lane cannot report would be
        permanently unrated.

        TWO KINDS OF STALE, and the second is the one the directive was issued over:

          age        the probe itself is old. `Reading.lost` already decides this and
                     it is reused rather than re-implemented.
          no session THE PROBE TIMESTAMP CAN BE FRESH WHILE THE NUMBER BEHIND IT IS
                     NOT. A session-derived reader takes its snapshot from rollout
                     files written BY sessions of that harness, so with none live it
                     re-reads the same old snapshot and stamps it now. On 2026-09-16
                     codex read 59% used at 9% elapsed -- a 6.5x pace, the most
                     alarming number on the host -- while zero codex agents had been
                     live for hours and the limit had since been reset. Age alone
                     could not see it, because the age was fine.

        The second check is OPT-IN per lane (`reading_needs_live_session = true`),
        never inferred from the lane name or the source string. The fleet view
        transports readings between hosts and rewrites `source`, so keying on the
        source would work locally and quietly stop working across the fleet -- which
        is precisely where this matters.
        """
        now = time.time() if now is None else now
        counts = self.counts(local_agents)
        live_by_harness = {}
        rows = [r for r in self.agents if local_agents is None or r['host'] != self.local]
        if local_agents is not None:
            rows += local_agents
        for row in rows:
            if row['live'] and not row.get('estimated'):
                h = row.get('account') or row.get('harness')
                live_by_harness[h] = live_by_harness.get(h, 0) + 1
        out = []
        for name, g in self.governors.items():
            policy = g.policy
            reading = g.reader.read_all().get(gov.SEVEN_DAY)
            if reading is None:
                out.append(balance_mod.LanePace(
                    lane=name, unrated_why='no seven_day reading'))
                continue
            lost = reading.lost(now, policy.max_age_seconds)
            pace_cfg = policy.pace_for(gov.SEVEN_DAY)
            length = (pace_cfg.window_length() if pace_cfg
                      else gov.WINDOW_LENGTH_S.get(gov.SEVEN_DAY))
            ratio, why = gov.pace_ratio(reading.pct if reading.pct is not None else 0.0,
                                        reading.reset_at, now, length)
            stale = lost or ''
            if not stale and getattr(policy, 'reading_needs_live_session', False):
                # The harnesses that feed this lane. `lane()` is the same mapping the
                # launch gate uses, so this cannot drift away from it.
                feeders = [h for h in live_by_harness if self.lane(h) == name]
                if not feeders:
                    age = int(now - reading.at) if reading.at else None
                    stale = ('no live session of this harness to refresh a '
                             'session-derived reading'
                             + (f' (stamped {age}s ago)' if age is not None else ''))
            out.append(balance_mod.LanePace(lane=name, ratio=ratio,
                                            unrated_why=why, stale_why=stale))
        return out

    def balance(self, now=None, local_agents=None, band=None):
        """Which lane to feed next, or why we cannot say. NEVER holds anything."""
        if band is None:
            band = balance_mod.DEFAULT_BAND
            for g in self.governors.values():
                configured = getattr(g.policy, 'balance_band', None)
                if configured:
                    band = configured
                    break
        return balance_mod.balance(self.lane_paces(now, local_agents), band)

    def admits_launch(self, harness, local_agents=None, *, administrators=(), target=None):
        if self.errors:
            return self.fallback()
        lane = self.lane(harness)
        governor = self.governors.get(lane)
        if governor is None:
            return 'account governor unconfigured for ' + harness if self.governors else ''
        verdict = governor.evaluate(persist=False)
        if verdict.frozen or verdict.drains:
            return ((verdict.alarm or verdict.why or 'account governor holds launches')
                    + '; no account-governor override; --despite-hold covers gaming/quiet-time only')
        rows = [r for r in self.agents
                if local_agents is None or r['host'] != self.local]
        if local_agents is not None:
            rows += local_agents
        rows = [r for r in rows
                if self.lane(r.get('account') or r['harness']) == lane]
        return launch_capacity_refusal(
            lane, verdict.max_agents, rows, administrators=administrators, target=target)


def launch_capacity_refusal(lane, cap, rows, *, administrators=(), target=None):
    """Preserve missing administrators' slots INSIDE the existing account cap.

    Identities come from the governed roster, not role claims in peer process
    rows. A running administrator consumes its reservation like any other slot.
    The total cap is still checked first, including for administrator repair.
    """
    if cap is None:
        return ''
    live = [row for row in rows if row['live']]
    count = len(live)
    if count >= cap:
        return (f'account governor {lane}: {count} live across hosts; '
                f'launch would count {count + 1}/{cap} (max_agents cap). '
                'No account-cap override; stop an agent in this account to free a slot. '
                '--despite-hold covers the gaming/quiet-time hold only.')
    administrators = set(administrators)
    occupied = {(row['host'], row['name']) for row in live}
    vacant = administrators - occupied
    if target not in administrators and count + len(vacant) >= cap:
        return (f'account governor {lane}: {count}/{cap} slots occupied; '
                f'{len(vacant)} slot(s) reserved for offline administrators. '
                'Launch an administrator or free a non-administrator slot; '
                '--despite-hold does not override account capacity.')
    return ''


class FreshestReader:
    """Immutable per-invocation observations with reproducible host provenance.

    The producer's timestamp decides freshness, never the time an SSH response
    arrives. A newer FAILED probe must remain a failed probe; filtering it out
    would turn a transport recovery mechanism into stale-success laundering.
    Governor.evaluate remains responsible for age, rotation grace and fail-safe
    policy. Missing timestamps survive only when no dated observation exists,
    and remain unaged (therefore unusable) at that gate.
    """

    def __init__(self, observations: Mapping[str, Mapping[str, Reading]]):
        selected: dict[str, tuple[float, str, Reading]] = {}
        for host, windows in sorted(observations.items()):
            for window, reading in windows.items():
                if not isinstance(reading, Reading):
                    raise GovernorError(f"invalid reading for {host}/{window}")
                stamp = reading.at
                if stamp is not None and (
                        isinstance(stamp, bool) or not isinstance(stamp, (float, int))
                        or not math.isfinite(stamp)):
                    raise GovernorError(f"invalid probe timestamp for {host}/{window}")
                rank = float('-inf') if stamp is None else stamp
                # Equal timestamps select the same host regardless of which
                # machine is asking or which response finished first.
                if window not in selected or rank > selected[window][0]:
                    selected[window] = (rank, host, reading)
        self._readings = {window: value[2] for window, value in selected.items()}
        self.provenance = {window: value[1] for window, value in selected.items()}

    def read_all(self) -> dict[str, Reading]:
        return dict(self._readings)
