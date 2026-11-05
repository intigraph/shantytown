"""Opt-in Claude file-memory lifecycle, not a daemon or a native overwrite.

All work runs inside the bounded memory worker. Deployment configuration owns
one explicit source/outbox/staging plan per crew member. The caller's card,
selected account and server principal must agree; a role name is not an owner.
Existing sources and generations remain recoverable, including late edits.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import time

from .memory_files import snapshot, stage
from .memory_outbox import Outbox, _bytes
from .memory_remote import Client, Owner, Unproven, _json, _export_files
from .memory_sync import step, _locked, _load, _projection


@dataclass(frozen=True)
class Plan:
    enabled: bool = False
    server: str = ''
    deployment: str = ''
    project: str = ''
    account: str = ''
    source: str = ''
    outbox: str = ''
    staging: str = ''


def parse(table):
    if not isinstance(table, dict):
        raise Unproven('memory must be a table of crew plans')
    result = {}
    for name, value in table.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', name):
            raise Unproven('memory plan crew name invalid')
        if not isinstance(value, dict) or set(value) - set(Plan.__dataclass_fields__):
            raise Unproven('memory plan has unknown fields')
        plan = Plan(**value)
        if type(plan.enabled) is not bool:
            raise Unproven('memory enabled must be boolean')
        if any(not isinstance(getattr(plan, key), str) for key in Plan.__dataclass_fields__ if key != 'enabled'):
            raise Unproven('memory plan fields must be text')
        if plan.enabled:
            Client(plan.server, Owner(plan.deployment, plan.project, 'urn:memory:validation'))
            for key in ('source', 'outbox', 'staging'):
                if not Path(getattr(plan, key)).is_absolute():
                    raise Unproven('memory plan directories must be absolute')
            paths = [Path(value) for value in (plan.source, plan.outbox, plan.staging)]
            if any(a == b or a in b.parents or b in a.parents
                   for number, a in enumerate(paths) for b in paths[number + 1:]):
                raise Unproven('memory source, outbox and staging must not overlap')
        result[name] = plan
    return result


def _selected(root, agent):
    from .config import load
    from .files import FilesRegistry
    from .accounts import selected
    cfg = load(root)
    plan = cfg.memory.get(agent)
    if plan is None or not plan.enabled:
        return None
    card = FilesRegistry(Path(root) / 'crew').get(agent)
    program = card.harness or cfg.harness_by_role.get(card.role) or cfg.harness_default or 'claude'
    account = selected(card, cfg)
    actual_account = account.name if account else 'legacy'
    if program != 'claude' or plan.account and actual_account != plan.account:
        raise Unproven('native memory adapter or selected account unsupported')
    plan = replace(plan, account=actual_account)
    client = Client.for_agent(root, agent, plan.server, plan.deployment, plan.project)
    paths = [Path(value).resolve(strict=True) for value in (plan.source, plan.outbox, plan.staging)]
    if any(a == b or a in b.parents or b in a.parents
           for number, a in enumerate(paths) for b in paths[number + 1:]):
        raise Unproven('memory directories alias or overlap')
    # A staged generation and its settings may contain private source/metadata;
    # they must never be staged inside the source tree or another crew's root.
    for path in (plan.outbox, plan.staging):
        resolved = Path(path).resolve()
        if any((parent / '.git').exists() for parent in (resolved, *resolved.parents)):
            raise Unproven('private memory state cannot be stored in a Git checkout')
        fd = Outbox(Path(path), client.owner)._open()
        os.close(fd)
    return plan, client


_NATIVE = 'memory-native.json'
_GENERATION = re.compile(r'memory-generation-[a-f0-9]{32}\Z')


def _identity(plan, client):
    return hashlib.sha256(_bytes(dict(owner=client.owner.wire(),
        source=plan.source, staging=plan.staging))).hexdigest()


def _native(outbox, fd, plan, client):
    raw = outbox._read(fd, _NATIVE)
    if raw is None:
        return None, Path(plan.source), dict(identity=_identity(plan, client), generation=None, head=None, pending=None)
    value = _json(raw)
    if (not isinstance(value, dict) or set(value) != {'identity', 'generation', 'head', 'pending'}
            or value['identity'] != _identity(plan, client)
            or not _generation(value['generation']) or not _head(value['head'])
            or not _pending(value['pending'])):
        raise Unproven('native memory selection identity unproven')
    source = Path(plan.source) if value['generation'] is None else Path(plan.staging) / value['generation']
    return raw, source, value


def _generation(value):
    return value is None or isinstance(value, str) and _GENERATION.fullmatch(value) is not None


def _head(value):
    return value is None or isinstance(value, str) and re.fullmatch(r'urn:quipu:memory:snapshot:[a-f0-9]{64}', value) is not None


def _pending(value):
    return value is None or (isinstance(value, dict) and set(value) == {'generation', 'head'}
        and value['generation'] is not None and _generation(value['generation']) and _head(value['head']))


def _current(outbox, plan, client):
    with _locked(outbox) as fd:
        _, source, _ = _native(outbox, fd, plan, client)
    return source


def synchronize(plan, client):
    outbox = Outbox(Path(plan.outbox), client.owner)
    source = _current(outbox, plan, client)
    _record(outbox, status='running', last_trigger=time.time())
    observed = []
    def capture():
        files = snapshot(source)
        observed.append(hashlib.sha256(_bytes([
            dict(path=file.path, sha256=file.sha256) for file in files])).hexdigest())
        return files
    try:
        result = step(outbox, client, capture, harness='claude',
                      account=plan.account, max_new=1)
    except Exception:
        _record(outbox, status='unknown')
        raise
    with _locked(outbox) as fd:
        live = _liveness(outbox, fd)
        now = time.time()
        live.update(status=result['status'], producer_coverage=(
            'complete_bounded_source' if observed else 'not_scanned_active_batch'))
        if observed:
            live['producer_last_scan'] = now
            if live.get('producer_source_sha256') != observed[0]:
                live.update(producer_source_sha256=observed[0], producer_last_change=now)
        head = result['accepted_head']
        if head is not None and live.get('ingest_accepted_head') != head:
            live.update(ingest_accepted_head=head, ingest_last_advance=now)
        _write_liveness(outbox, fd, live)
    return result


def _liveness(outbox, fd):
    raw = outbox._read(fd, 'memory-liveness.json')
    value = dict(owner=outbox.owner.wire()) if raw is None else _json(raw)
    if not isinstance(value, dict) or value.get('owner') != outbox.owner.wire():
        raise Unproven('memory liveness owner mismatch')
    return value


def _write_liveness(outbox, fd, value):
    name = 'memory-liveness.json'
    _save_record(outbox, fd, name, outbox._read(fd, name), value)


def _record(outbox, **updates):
    with _locked(outbox) as fd:
        value = _liveness(outbox, fd)
        value.update(updates)
        _write_liveness(outbox, fd, value)


def prepare(plan, client, settings):
    """Reconcile before selecting a NEW generation for one future launch.

    Never replace a native file or a role settings file. A late external edit
    stays in the old generation; the final reread detects observed races, not
    arbitrary edits after handoff. Retained old roots require explicit conflict
    reconciliation if an external editor continues writing there afterwards.
    """
    outbox = Outbox(Path(plan.outbox), client.owner)
    current = _current(outbox, plan, client)
    _native_settings_allowed(settings, plan, current)
    result = synchronize(plan, client)
    if result['status'] == 'pending':
        # A bounded partial upload is not permission to export a partial owner
        # snapshot. Keep the existing native source usable while ordinary hooks
        # resume its frozen batch. No new generation is selected here.
        with _locked(outbox) as fd:
            _, source, native = _native(outbox, fd, plan, client)
            marker = native['generation'] or 'original'
            return _artifact(outbox, fd, settings, source, result['accepted_head'],
                             marker=marker, ingest='pending', native_files='UNCHANGED_EXISTING_SOURCE')
    with _locked(outbox) as fd:
        previous, source, native = _native(outbox, fd, plan, client)
        _, sync_state = _load(outbox, fd)
        if sync_state['active_batch'] is not None:
            raise Unproven('native memory batch changed; no selection')
        projection, head = _projection(client)
        if head != sync_state['accepted_head']:
            raise Unproven('native memory projection changed; no selection')
        local = snapshot(source)
        remote = _export_files(projection['export'], client.owner, allow_empty=True)
        if local != remote:
            raise Unproven('source changed after frozen batch; preserve both versions')
        pending = native['pending']
        if pending is not None and pending['head'] == head:
            generation = Path(plan.staging) / pending['generation']
            if snapshot(generation) != remote:
                raise Unproven('pending native generation changed; preserve both versions')
        elif previous is None or native['head'] != head:
            generation = stage(remote, Path(plan.staging))
            if snapshot(source) != local:
                raise Unproven('source changed during handoff; new generation unselected')
            native['pending'] = dict(generation=generation.name, head=head)
            # Preparation does not change the active source. Only the actual
            # SessionStart carrying this pending selection can acknowledge it.
            _save_native(outbox, fd, previous, native)
        else:
            generation = source
        return _artifact(outbox, fd, settings, generation, head,
                         marker=generation.name, ingest=result['status'],
                         native_files='NEW_GENERATION_ONLY')


def _native_settings_allowed(settings, plan, source):
    if ('autoMemoryEnabled' in settings and settings['autoMemoryEnabled'] is not True
            or os.environ.get('CLAUDE_CODE_DISABLE_AUTO_MEMORY') == '1'
            or settings.get('env', {}).get('CLAUDE_CODE_DISABLE_AUTO_MEMORY') == '1'):
        raise Unproven('native memory is explicitly disabled; no override')
    selected = settings.get('autoMemoryDirectory')
    if selected is not None and (not isinstance(selected, str)
            or Path(selected).expanduser().resolve() not in {Path(plan.source).resolve(), source.resolve()}):
        raise Unproven('existing native memory directory differs from declared source')


def _artifact(outbox, fd, settings, generation, head, *, marker, ingest, native_files):
    raw = _bytes(_emitted(settings, generation, marker=marker))
    name = 'memory-settings-' + hashlib.sha256(raw).hexdigest() + '.json'
    outbox._install(fd, name, raw)
    return dict(status='prepared', settings=str(outbox.root / name), generation=str(generation),
                head=head, ingest_status=ingest, native_files=native_files)


def _emitted(settings, generation, *, marker=None):
    emitted = copy.deepcopy(settings)
    emitted['autoMemoryDirectory'] = str(generation)
    emitted['autoMemoryEnabled'] = True
    emitted.setdefault('env', {})['SHANTY_MEMORY_GENERATION'] = marker or generation.name
    return emitted


def _save_native(outbox, fd, previous, value):
    _save_record(outbox, fd, _NATIVE, previous, value)


def _save_record(outbox, fd, name, previous, value):
    # _save's state machine is deliberately fixed to memory-sync.json. Native
    # selection is a separate journal; use the same expected-byte discipline.
    import secrets
    if outbox._read(fd, name) != previous:
        raise Unproven('native memory journal changed')
    temporary = 'native-' + secrets.token_hex(16) + '.tmp'
    data = _bytes(value)
    outbox._install(fd, temporary, data)
    try:
        if outbox._read(fd, name) != previous:
            raise Unproven('native memory journal changed')
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
        if outbox._read(fd, name) != data:
            raise Unproven('native memory journal readback differs')
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def acknowledge(plan, client, generation, event):
    if not isinstance(generation, str) or generation != 'original' and not _GENERATION.fullmatch(generation):
        raise Unproven('native memory launch selection missing')
    outbox = Outbox(Path(plan.outbox), client.owner)
    with _locked(outbox) as fd:
        raw, _, native = _native(outbox, fd, plan, client)
        pending = native['pending']
        if generation == 'original' and native['generation'] is None:
            if event == 'start' and raw is None:
                _save_native(outbox, fd, raw, native)
            return  # Existing source is not proof of Quipu projection/start.
        if event == 'start' and pending is not None and pending['generation'] == generation:
            snapshot(Path(plan.staging) / generation)
            native.update(generation=generation, head=pending['head'], pending=None)
            _save_native(outbox, fd, raw, native)
            live = _liveness(outbox, fd)
            live.update(projection_last_start=time.time(), projection_head=native['head'],
                        projection_generation=generation)
            _write_liveness(outbox, fd, live)
        elif native['generation'] != generation:
            raise Unproven('native memory source differs from active launch; preserve both roots')


def _settings(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.getuid() or before.st_mode & 0o022
                or before.st_size > 1024 * 1024):
            raise Unproven('native settings source unsafe')
        raw = stream.read(1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    from .memory_files import _version
    if len(raw) > 1024 * 1024 or _version(before) != _version(after):
        raise Unproven('native settings changed')
    value = _json(raw)
    if not isinstance(value, dict) or not isinstance(value.get('env', {}), dict):
        raise Unproven('native settings malformed')
    return value


def execute(args):
    selection = _selected(args.root, args.agent)
    if selection is None:
        return dict(status='disabled')
    plan, client = selection
    if args.memory_action == 'lifecycle':
        if args.lifecycle_event not in {'start', 'stop'}:
            raise Unproven('native memory lifecycle event invalid')
        acknowledge(plan, client, args.generation, args.lifecycle_event)
        return synchronize(plan, client)
    return prepare(plan, client, _settings(args.settings))


def prepare_launch(root, card, settings_path):
    from .config import load
    if root is None:
        return settings_path
    cfg = load(root)
    if not cfg.memory.get(card.name, Plan()).enabled:
        return settings_path
    program = card.harness or cfg.harness_by_role.get(card.role) or cfg.harness_default or 'claude'
    if program != 'claude':
        # Unsupported generated writeback must not prevent the existing Codex
        # read-only startup bridge or invent a native directory for it.
        return settings_path
    from .memory_deadline import _run
    args = argparse.Namespace(root=Path(root), agent=card.name, settings=Path(settings_path))
    result = _run(args, 'prepare-native', seconds=2.0, result_limit=4096)
    if result.get('status') != 'prepared' or not isinstance(result.get('settings'), str):
        raise Unproven('native memory launch unproven')
    return result['settings']


def selected_settings(root, card, settings_path):
    """Read-only expected artifact for launch-stamp checks; no remote request."""
    if root is None:
        return settings_path
    from .config import load
    cfg = load(root)
    program = card.harness or cfg.harness_by_role.get(card.role) or cfg.harness_default or 'claude'
    if not cfg.memory.get(card.name, Plan()).enabled or program != 'claude':
        return settings_path
    plan, client = _selected(root, card.name)
    outbox = Outbox(Path(plan.outbox), client.owner)
    with _locked(outbox) as fd:
        _, source, native = _native(outbox, fd, plan, client)
        if native['generation'] is None and outbox._read(fd, _NATIVE) is None:
            return settings_path
        marker = native['generation'] or 'original'
        raw = _bytes(_emitted(_settings(Path(settings_path)), source, marker=marker))
        name = 'memory-settings-' + hashlib.sha256(raw).hexdigest() + '.json'
        if outbox._read(fd, name) != raw:
            raise Unproven('native settings artifact missing or base changed')
        return str(outbox.root / name)


def hooks(root, event):
    from .config import load_or_default
    if root is None:
        return []
    cfg, error = load_or_default(root)
    # Preserve the emitter's existing malformed-config contract: its ordinary
    # warning remains visible, while no uncertain memory plan is activated.
    if error or not any(plan.enabled for plan in cfg.memory.values()):
        return []
    command = shlex.join([sys.executable, '-m', 'shantytown.memory_lifecycle',
                          '--root', str(Path(root).resolve()), '--event', event])
    return [{'hooks': [{'type': 'command', 'command': command, 'timeout': 3}]}]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--event', required=True, choices=('start', 'stop'))
    args = parser.parse_args(argv)
    agent = os.environ.get('SHANTY_AGENT')
    if not agent:
        return 0
    from .memory_deadline import _run
    try:
        result = _run(argparse.Namespace(root=Path(args.root), agent=agent,
                      generation=os.environ.get('SHANTY_MEMORY_GENERATION'), lifecycle_event=args.event),
                      'lifecycle', seconds=2.0, result_limit=4096)
        if result.get('status') != 'disabled':
            print('st memory: ' + json.dumps(result, sort_keys=True))
    except (OSError, ValueError):
        print('st memory: UNKNOWN; source/outbox retained; no retry', file=sys.stderr)
    return 0  # Memory transport must never block the harness Stop decision.


if __name__ == '__main__':
    raise SystemExit(main())
