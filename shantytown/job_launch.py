"""Fixed, operator-prepared job capabilities; never a general sudo command API.

The root-owned manifest names one dedicated UID, one immutable job and its
already-enrolled private home. No caller command, environment or account name
crosses the privilege boundary. Used UIDs are not recycled between principals.
Installation and native isolation acceptance remain separate operator steps.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import stat
import subprocess
import sys

from .actor_identity import IdentityError

BASE = (Path('/Library/Application Support/Shantytown/jobs') if sys.platform == 'darwin'
        else Path('/etc/shantytown/jobs'))
HELPER = Path('/usr/local/libexec/st-job-launcher')
OWNER = 0
_NAME = re.compile(r'eph-(review|merge|triage|task)-[0-9a-f]{6}')
FIELDS = {'version', 'principal', 'controller_uid', 'uid', 'gid', 'username',
          'home', 'root', 'controller_root', 'workspace', 'settings', 'harness', 'request', 'argv', 'environment'}
ENVIRONMENT = {'PATH', 'LANG', 'LC_ALL', 'TERM', 'CODEX_HOME', 'CLAUDE_CONFIG_DIR'}


def protected(path, *, directory=False):
    """Require an immutable chain, including parents, before trusting root input."""
    path = Path(path)
    if not path.is_absolute():
        raise IdentityError('job capability path must be absolute')
    for parent in [*reversed(path.parents), path]:
        meta = parent.lstat()
        if (sys.platform == 'darwin' and parent == Path('/var')
                and stat.S_ISLNK(meta.st_mode) and meta.st_uid == OWNER
                and os.readlink(parent) in ('private/var', '/private/var')):
            # macOS's fixed root-owned OS alias is not a job-controlled link.
            # Validate its canonical target too; all other symlinks still fail.
            protected(Path('/private/var'), directory=True)
            continue
        if (stat.S_ISLNK(meta.st_mode) or meta.st_uid != OWNER or meta.st_mode & 0o022
                or (parent != path or directory) and not stat.S_ISDIR(meta.st_mode)):
            raise IdentityError('job capability/code path must be root-owned and non-writable')
    if not directory and not stat.S_ISREG(path.lstat().st_mode):
        raise IdentityError('job capability/code must be a regular file')


def load(name):
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise IdentityError('invalid registered job principal')
    path = BASE / (name + '.json')
    protected(path)
    # Open without following a replaced final component; parent ownership above
    # excludes a lower-privilege rename between validation and this open.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(stream.fileno())
        if meta.st_uid != OWNER or meta.st_mode & 0o022 or meta.st_size > 65536:
            raise IdentityError('invalid protected job manifest')
        raw = stream.read(65537)
    try:
        spec = json.loads(raw)
    except ValueError as error:
        raise IdentityError('invalid job manifest JSON') from error
    if (not isinstance(spec, dict) or set(spec) != FIELDS or spec['version'] != 1
            or spec['principal'] != name):
        raise IdentityError('invalid job manifest schema')
    for key in ('uid', 'gid', 'controller_uid'):
        if type(spec[key]) is not int or spec[key] < (10000 if key != 'controller_uid' else 1):
            raise IdentityError('job needs a dedicated protected UID/GID')
    if spec['gid'] != spec['uid']:
        raise IdentityError('job requires its own primary group')
    if spec['controller_uid'] == spec['uid']:
        raise IdentityError('job UID cannot be its controller')
    if not isinstance(spec['username'], str) or not re.fullmatch(r'_stjobs(?:_[0-9a-f]{6})?', spec['username']):
        raise IdentityError('only dedicated job accounts may be selected')
    if spec['harness'] not in ('codex', 'claude') or not isinstance(spec['request'], dict):
        raise IdentityError('invalid job request/harness')
    expected = {'job', 'item', 'repo', 'pr', 'checkout', 'head', 'request_id'}
    if set(spec['request']) != expected or not name.startswith('eph-' + str(spec['request']['job']) + '-'):
        raise IdentityError('job principal/request mismatch')
    for key in ('home', 'root', 'controller_root', 'workspace', 'settings'):
        value = spec[key]
        if (not isinstance(value, str) or not Path(value).is_absolute()
                or any(c in value for c in '\r\n\0') or '..' in Path(value).parts):
            raise IdentityError('invalid absolute job path')
    home = Path(spec['home'])
    if str(home) != '/var/lib/shantytown/agents/crew-' + name:
        raise IdentityError('job home must use the protected identity home convention')
    if spec['root'] != '/var/lib/shantytown/job-stores/' + name:
        raise IdentityError('job metadata root must be its own protected store')
    if (Path(spec['controller_root']).is_relative_to(Path(spec['root']))
            or Path(spec['root']).is_relative_to(Path(spec['controller_root']))):
        raise IdentityError('job metadata root and controller store must be separate')
    for key in ('workspace', 'settings'):
        if not Path(spec[key]).is_relative_to(home) or Path(spec[key]) == home:
            raise IdentityError('job state/settings must be private to its own home')
    argv = spec['argv']
    if (not isinstance(argv, list) or not argv or len(argv) > 128
            or any(not isinstance(x, str) or not x or len(x) > 8192 or '\0' in x for x in argv)
            or not Path(argv[0]).is_absolute()):
        raise IdentityError('invalid pinned job argv')
    env = spec['environment']
    if (not isinstance(env, dict) or set(env) - ENVIRONMENT
            or any(not isinstance(v, str) or '\0' in v for v in env.values())):
        raise IdentityError('job environment is not allowlisted')
    for key in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR'):
        if key in env and not Path(env[key]).is_relative_to(home):
            raise IdentityError('harness configuration must belong to the job')
    return spec, hashlib.sha256(raw).hexdigest()


def request_fields(req):
    return {key: getattr(req, key) for key in ('job', 'item', 'repo', 'pr', 'checkout', 'head', 'request_id')}


def inventory():
    """Validate the whole bounded plan, including direct helper admission."""
    protected(BASE, directory=True)
    plan_path = BASE / 'slots.json'
    protected(plan_path)
    fd = os.open(plan_path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(stream.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != OWNER
                or meta.st_mode & 0o022 or meta.st_size > 1024 * 1024):
            raise IdentityError('invalid protected host slot plan')
        plan = json.load(stream)
    if (not isinstance(plan, dict) or set(plan) != {'version', 'uid_min', 'uid_max', 'slots'}
            or type(plan['version']) is not int or plan['version'] != 1
            or type(plan['uid_min']) is not int or type(plan['uid_max']) is not int
            or not 10000 <= plan['uid_min'] <= plan['uid_max']
            or not isinstance(plan['slots'], dict) or not 1 <= len(plan['slots']) <= 1024):
        raise IdentityError('host needs an explicit bounded protected slot plan')
    for name, slot in plan['slots'].items():
        if (not _NAME.fullmatch(name) or not isinstance(slot, dict)
                or set(slot) != {'uid', 'sha256'} or type(slot['uid']) is not int
                or not plan['uid_min'] <= slot['uid'] <= plan['uid_max']
                or not isinstance(slot['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', slot['sha256'])):
            raise IdentityError('invalid protected host slot reservation')
    paths = sorted(BASE.glob('eph-*.json'))
    if {path.stem for path in paths} != set(plan['slots']):
        raise IdentityError('job manifests differ from the explicit host slot plan')
    seen_uids = set()
    seen_users = set()
    entries = []
    for path in paths:
        spec, digest = load(path.stem)
        if plan['slots'][path.stem] != {'uid': spec['uid'], 'sha256': digest}:
            raise IdentityError('job manifest changed from its host slot reservation')
        if spec['uid'] in seen_uids:
            raise IdentityError('a job UID cannot be shared or reused by another principal')
        if spec['username'] in seen_users:
            raise IdentityError('a job account cannot be shared between slots')
        seen_uids.add(spec['uid'])
        seen_users.add(spec['username'])
        entries.append((spec, digest))
    if any(spec['controller_uid'] in seen_uids for spec, _ in entries):
        raise IdentityError('a job UID cannot control another job')
    return entries


def select(req, *, root, harness, used, native_probe=True):
    """Read-only selection. An absent/partial plan never falls back to caller UID."""
    candidates = []
    for spec, digest in inventory():
        if (spec['request'] == request_fields(req) and spec['controller_root'] == str(Path(root).resolve())
                and spec['harness'] == harness and spec['controller_uid'] == os.geteuid()
                and spec['principal'] not in used):
            candidates.append((spec, digest))
    if len(candidates) != 1:
        raise IdentityError('job needs exactly one unused protected launch capability')
    spec, digest = candidates[0]
    protected(HELPER)
    if not native_probe:
        return spec, digest  # preview only; no UID proof and no ledger mutation
    answer = subprocess.run(['/usr/bin/sudo', '-n', '--', str(HELPER), 'check', spec['principal'], digest],
                            capture_output=True, text=True, timeout=30,
                            env={'PATH': '/usr/bin:/bin'})
    # The helper is installed with a narrow privilege mechanism by the operator;
    # a normal unprivileged executable must refuse, not pretend to switch UID.
    if answer.returncode != 0 or answer.stdout.strip() != 'READY ' + digest:
        raise IdentityError('protected job launcher did not verify the UID boundary')
    return spec, digest


def for_card(root, card):
    from . import ephemeral
    if not ephemeral.is_ephemeral_name(card.name) or not getattr(card, 'dangerous', False):
        return None
    rec = ephemeral.read(root, card.name)
    binding = (rec or {}).get('uid_binding')
    if not isinstance(binding, dict) or set(binding) != {'sha256', 'uid'}:
        raise IdentityError('unattended job has no protected launch binding')
    spec, digest = load(card.name)
    if (digest != binding['sha256'] or spec['uid'] != binding['uid']
            or spec['workspace'] != card.workspace or spec['controller_root'] != str(Path(root).resolve())
            or spec['harness'] != card.harness):
        raise IdentityError('job launch capability changed since admission')
    return spec, digest


def command(spec, digest):
    protected(HELPER)
    return shlex.join(['/usr/bin/sudo', '-n', '--', str(HELPER), 'launch', spec['principal'], digest])


def check_native(spec, *, consumed_digest=None, lifecycle=False):
    """Called only by the separate privileged, immutable launcher."""
    from . import actor_identity
    if sys.platform != 'darwin' and not sys.platform.startswith('linux'):
        raise IdentityError('unsupported native job platform')
    row = actor_identity._policy(actor_identity.POLICY_PATH, for_principal=spec['principal'])
    if row is None or row['uid'] != spec['uid'] or row['home'] != spec['home']:
        raise IdentityError('missing or mismatching protected actor binding')
    protected(row['sd'])
    account = pwd.getpwnam(spec['username'])
    if (account.pw_uid != spec['uid'] or account.pw_gid != spec['gid']
            or account.pw_dir != spec['home'] or account.pw_shell not in ('/usr/bin/false', '/bin/false', '/usr/sbin/nologin')):
        raise IdentityError('job account is absent or only partially provisioned')
    if not lifecycle:
        protected(Path(spec['root']), directory=True)
        controller_root = Path(spec['controller_root'])
        for parent in [*reversed(controller_root.parents), controller_root]:
            meta = parent.lstat()
            if (not stat.S_ISDIR(meta.st_mode) or meta.st_uid not in (OWNER, spec['controller_uid'])
                    or meta.st_mode & 0o022):
                raise IdentityError('controller store has a mutable or foreign path component')
        if controller_root.lstat().st_mode & 0o077:
            raise IdentityError('controller store must be private to its controller UID')
        for key in ('home', 'workspace'):
            path = Path(spec[key])
            meta = path.lstat()
            if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != spec['uid'] or meta.st_mode & 0o077:
                raise IdentityError('job home/workspace is not private to its UID')
        protected(Path(spec['home']).parent.resolve(), directory=True)
        settings = Path(spec['settings']).lstat()
        if not stat.S_ISREG(settings.st_mode) or settings.st_uid != spec['uid'] or settings.st_mode & 0o077:
            raise IdentityError('job settings must be a private job-owned regular file')
    protected(spec['argv'][0])
    receipts = BASE / 'used'
    protected(receipts, directory=True)
    used = list(receipts.glob('*.json'))
    if len(used) > 1024:
        raise IdentityError('too many retained UID receipts')
    matched = False
    for path in used:
        protected(path)
        try:
            old = json.loads(path.read_text())
        except ValueError as error:
            raise IdentityError('unknown prior UID receipt') from error
        if not isinstance(old, dict) or type(old.get('uid')) is not int:
            raise IdentityError('unknown prior UID receipt')
        if old['uid'] == spec['uid']:
            if consumed_digest is None or old != {
                    'uid': spec['uid'], 'principal': spec['principal'], 'sha256': consumed_digest}:
                raise IdentityError('job UID already used; retain its receipt')
            if matched:
                raise IdentityError('duplicate consumed job UID receipt')
            matched = True
    if consumed_digest is not None and not matched:
        raise IdentityError('cannot stop an unreserved job UID')

    # Existing UID bindings remain authoritative. No username-exists readiness
    # and no credentials from the controller's home or environment.
    return row


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(argv) != 3 or argv[0] not in ('check', 'launch', 'stop', 'submit', 'poll') or not re.fullmatch(r'[0-9a-f]{64}', argv[2]):
            raise IdentityError('expected fixed operation, job principal and manifest digest')
        if os.geteuid() != 0:
            raise IdentityError('job launcher requires its separately admitted privileged service')
        protected(Path(__file__).absolute())
        spec, digest = load(argv[1])
        if argv[2] != digest:
            raise IdentityError('job capability digest changed')
        # Do not trust the caller to have used select(): sudo invokes this
        # fixed helper directly, so it must enforce the entire inventory too.
        if (spec, digest) not in inventory():
            raise IdentityError('job capability is absent from the protected inventory')
        # sudo supplies this only AFTER its kernel privilege boundary. An
        # unprivileged caller spoofing environment is refused above; root is
        # already trusted. The reviewed sudoers entry names only this helper,
        # grants controller operations only to controller UIDs; a job's narrow
        # rule may grant only submit with its exact principal and digest.
        caller = os.environ.get('SUDO_UID', '')
        expected_uid = spec['uid'] if argv[0] == 'submit' else spec['controller_uid']
        if not caller.isdecimal() or int(caller) != expected_uid:
            raise IdentityError('job launcher lacks an admitted controller UID')
        if argv[0] in ('submit', 'poll'):
            from . import job_mailbox
            check_native(spec, consumed_digest=digest, lifecycle=True)
            if argv[0] == 'submit':
                import signal
                def input_timeout(_signal, _frame):
                    raise IdentityError('job message input timed out')
                prior_handler = signal.signal(signal.SIGALRM, input_timeout)
                signal.alarm(5)
                try:
                    raw = sys.stdin.buffer.read(16385)
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, prior_handler)
                if len(raw) > 16384:
                    raise IdentityError('job message exceeds input bound')
                job_mailbox.submit(BASE, spec, digest, json.loads(raw), trust=protected)
                print('QUEUED ' + digest)
            else:
                print(json.dumps(job_mailbox.read(BASE, spec, digest, trust=protected)))
            return 0
        if argv[0] == 'stop':
            check_native(spec, consumed_digest=digest, lifecycle=True)
            stop_native(spec)
            print('STOPPED ' + digest)
            return 0
        check_native(spec)
        if argv[0] == 'check':
            probe(spec)
            print('READY ' + digest)
            return 0
        import fcntl
        protected(BASE / 'used', directory=True)
        lock_fd = os.open(BASE / 'used' / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock_fd, 'r+') as lock:
            meta = os.fstat(lock.fileno())
            if meta.st_uid != OWNER or meta.st_mode & 0o077 or not stat.S_ISREG(meta.st_mode):
                raise IdentityError('invalid protected job UID lock')
            fcntl.flock(lock, fcntl.LOCK_EX)
            consume(spec, digest)
            execute(spec)
    except (IdentityError, OSError, KeyError, ValueError, subprocess.SubprocessError) as error:
        print('refused: ' + type(error).__name__, file=sys.stderr)
        return 1


def consume(spec, digest):
    """A failed drop/exec consumes its slot too; never blindly recycle an OS UID."""
    receipts = BASE / 'used'
    protected(receipts, directory=True)
    paths = list(receipts.glob('*.json'))
    if len(paths) > 1024:
        raise IdentityError('job UID receipt inventory exceeds its bound')
    for path in paths:
        protected(path)
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or type(data.get('uid')) is not int:
            raise IdentityError('unknown prior job UID use')
        if data['uid'] == spec['uid']:
            raise IdentityError('job UID was already used; no principal reuse')
    # A single host lock serializes the UID check with every reservation.
    # main holds this lock; the O_EXCL record additionally prevents same-name
    # retry after an exec failure. All records survive rollback.
    fd = os.open(receipts / (spec['principal'] + '.json'),
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'uid': spec['uid'], 'principal': spec['principal'], 'sha256': digest}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(receipts, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def drop_identity(spec):
    """No return in the caller identity, including a failed partial switch."""
    os.setgroups([])
    os.setgid(spec['gid'])
    os.setuid(spec['uid'])
    if (os.getuid() != spec['uid'] or os.geteuid() != spec['uid']
            or os.getgid() != spec['gid'] or os.getegid() != spec['gid'] or os.getgroups()):
        raise IdentityError('native job user switch did not establish the requested identity')
    if sys.platform.startswith('linux'):
        import ctypes
        # Preserve existing Linux no-new-privileges posture after dropping all
        # root credentials; a failure must never become a caller-UID launch.
        if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0) != 0:
            raise IdentityError('could not prohibit privilege gain')


def probe(spec):
    """A short disposable child proves the native switch before retry teardown.

    This is privileged *runtime* qualification, never called by source tests on
    the actual host. It runs no job, shell or login; it does perform the
    existing pinned identity-attestation protocol using the job's own key.
    """
    import time
    import signal
    child = os.fork()
    if child == 0:
        try:
            attest_job(spec)
        except BaseException:
            os._exit(1)
        os._exit(0)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        pid, status = os.waitpid(child, os.WNOHANG)
        if pid:
            if os.waitstatus_to_exitcode(status) != 0:
                raise IdentityError('native disposable UID switch failed')
            return
        time.sleep(0.02)
    os.kill(child, signal.SIGKILL)
    os.waitpid(child, 0)
    raise IdentityError('native disposable UID switch timed out')


def attest_job(spec):
    """Attest the job's own key only after dropping all controller identity."""
    from . import actor_identity
    drop_identity(spec)
    os.environ.clear()
    os.environ.update(HOME=spec['home'], PATH='/usr/bin:/bin', LC_ALL='C')
    os.chdir(spec['home'])
    if actor_identity.authenticated_actor() != spec['principal']:
        raise IdentityError('job key does not attest the protected job principal')


def execute(spec):
    """Irreversible native UID drop on Linux/macOS; never use a fallback user."""
    import resource
    if sys.platform != 'darwin' and not sys.platform.startswith('linux'):
        raise IdentityError('unsupported native UID boundary')
    maximum = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    if maximum == resource.RLIM_INFINITY or maximum > 1048576:
        raise IdentityError('cannot bound inherited file descriptors')
    drop_identity(spec)
    env = dict(spec['environment'], HOME=spec['home'], USER=spec['username'],
               LOGNAME=spec['username'], SHANTY_AGENT=spec['principal'], SHANTY_ROOT=spec['root'])
    os.chdir(spec['workspace'])
    os.closerange(3, maximum)
    os.execve(spec['argv'][0], spec['argv'], env)


def running_uid(uid):
    """Portable ps snapshot; unknown/malformed output is never an empty UID."""
    proc = subprocess.Popen(['/bin/ps', '-axo', 'uid=,pid=,stat='],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    try:
        output, _ = proc.communicate(timeout=2)
    except BaseException:
        proc.kill()
        proc.communicate()
        raise
    if proc.returncode != 0 or len(output) > 4 * 1024 * 1024 or not output.strip():
        raise IdentityError('cannot establish native UID process state')
    result = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) != 3 or not fields[0].isdecimal() or not fields[1].isdecimal():
            raise IdentityError('malformed native UID process state')
        pid = int(fields[1])
        if int(fields[0]) == uid and pid not in (os.getpid(), proc.pid) and not fields[2].startswith('Z'):
            if pid <= 1:
                raise IdentityError('unsafe job process identity')
            result.append(pid)
    return result


def stop_uid(spec):
    """Run only after irreversible UID drop: kernel permission bounds signals.

    Session/ancestry/cwd do not matter. A PID recycled to another UID cannot be
    signalled by this child. UID slots must never be reused between principals.
    """
    import signal
    import time
    drop_identity(spec)
    for _ in range(10):
        pids = running_uid(spec['uid'])
        if not pids:
            return
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.05)
    raise IdentityError('job UID termination remains unproven')


def stop_native(spec):
    """Root waits; only the dropped child can signal. No root PID kill API."""
    import time
    child = os.fork()
    if child == 0:
        try:
            stop_uid(spec)
        except BaseException:
            os._exit(1)
        os._exit(0)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        pid, status = os.waitpid(child, os.WNOHANG)
        if pid:
            if os.waitstatus_to_exitcode(status) != 0:
                raise IdentityError('native job UID termination failed')
            return
        time.sleep(0.02)
    # Do not signal an unverified PID from root even on timeout. A hung child
    # leaves teardown/cap ENDING; the caller must retain that unknown result.
    raise IdentityError('native job UID termination timed out')


def stop(root, rec):
    binding = rec.get('uid_binding')
    spec, digest = load(rec['name'])
    if (binding != {'uid': spec['uid'], 'sha256': digest}
            or spec['controller_root'] != str(Path(root).resolve())):
        raise IdentityError('job stop binding changed')
    protected(HELPER)
    answer = subprocess.run(['/usr/bin/sudo', '-n', '--', str(HELPER), 'stop', spec['principal'], digest],
                            capture_output=True, text=True, timeout=35, env={'PATH': '/usr/bin:/bin'})
    if answer.returncode != 0 or answer.stdout.strip() != 'STOPPED ' + digest:
        raise IdentityError('job UID termination was not verified')


def mailbox_call(spec, digest, operation, value=None):
    """Fixed protocol only; no caller-selected commands, UID or environment."""
    if operation not in ('submit', 'poll'):
        raise IdentityError('invalid job mailbox operation')
    from . import job_mailbox
    protected(HELPER)
    raw = None if operation == 'poll' else json.dumps(job_mailbox.payload(value))
    if raw is not None and len(raw.encode()) > 16384:
        raise IdentityError('job message exceeds input bound')
    answer = subprocess.run(['/usr/bin/sudo', '-n', '--', str(HELPER), operation, spec['principal'], digest],
                            input=raw, capture_output=True, text=True, timeout=10,
                            env={'PATH': '/usr/bin:/bin'})
    if answer.returncode != 0 or len(answer.stdout.encode()) > job_mailbox.MAX_BYTES:
        raise IdentityError('job mailbox operation unproved')
    if operation == 'submit':
        if answer.stdout.strip() != 'QUEUED ' + digest:
            raise IdentityError('job message was not acknowledged')
        return None
    return job_mailbox.validate(json.loads(answer.stdout), spec, digest)


def poll(root, rec):
    spec, digest = load(rec['name'])
    if (rec.get('uid_binding') != {'uid': spec['uid'], 'sha256': digest}
            or spec['controller_root'] != str(Path(root).resolve())):
        raise IdentityError('job mailbox binding changed')
    return mailbox_call(spec, digest, 'poll')


def local_job():
    """Select the caller by protected kernel UID; environment is no selector."""
    from . import actor_identity, ephemeral
    row = actor_identity._policy(actor_identity.POLICY_PATH)
    if row is None or not ephemeral.is_ephemeral_name(row['principal']):
        return None
    spec, digest = load(row['principal'])
    if (spec['uid'] != os.geteuid() or row['home'] != spec['home']
            or actor_identity.authenticated_actor() != spec['principal']):
        raise IdentityError('caller is not the protected job principal')
    return spec, digest


if __name__ == '__main__':
    raise SystemExit(main())
