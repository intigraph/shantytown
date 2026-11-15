"""Host-scoped duty adapters; shares stranded-owner-work, not a second sweep."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from . import agent_hold
from .duties import Duties, validate
from .files import write_json_atomic
from .stopped import FilesStops


def bindings(root, cards, panes, inbox, tracker, host, registry):
    stops = FilesStops(Path(root) / 'stopped')

    def observe(name):
        card = cards.get(name)
        if card is None or card.host != host:
            return dict(state='unknown', generation='unscoped card')
        try:
            if registry.get(name) != card:
                return dict(state='unknown', generation='card changed')
        except LookupError:
            return dict(state='unknown', generation='card absent')
        state = panes.owner_state(card.pane)
        stop = stops.all().exact().get(name)
        hold = agent_hold.reason(root, name)
        generation = hashlib.sha256(json.dumps([
            name, card.pane, card.host,
            [stop.at, stop.by, stop.reason, stop.resume_at] if stop else None,
            hold], sort_keys=True).encode()).hexdigest()
        if state == 'down' and stop:
            return dict(state='operator-stopped', generation=generation, stopped_at=stop.at)
        if state == 'live' and hold:
            return dict(state='held', generation=generation)
        return dict(state=state if state in {'live', 'down'} else 'unknown',
                    generation=generation)

    def live(name):
        return observe(name)['state'] == 'live'

    def administrator():
        names = [c.name for c in cards.values()
                 if c.role == 'administrator' and c.host == host]
        if len(names) != 1:
            raise ValueError('duty administrator route UNKNOWN')
        return names[0]

    def ensure_issue(payload, target, key):
        create = getattr(tracker, 'create_duty_issue', None)
        if not callable(create):
            raise ValueError('idempotent duty repair adapter unsupported')
        return create(payload, target=target, key=key).id

    def notify(target, body, key):
        receipt = inbox.deliver_once(target, body, key, frm='st stranded-duty')
        seen = inbox.find_delivery(target, key)
        if seen is None or seen.id != receipt.id or seen.body != body:
            raise ValueError('duty page delivery UNKNOWN')

    return dict(observe=observe, live=live, administrator=administrator,
                ensure_issue=ensure_issue, notify=notify)


def sweep(root, cards, panes, inbox, tracker, host, registry, *, now, release, dry_run=False):
    duties = Duties(root)
    if dry_run:
        if not duties.path.exists():
            # Unenrolled deployments retain the item-only preview contract.
            # Their separate duty summary remains UNKNOWN, never healthy zero.
            return []
        from .duty_discovery import job_bindings
        inventory = duties.load()
        inventory['entries'] = [r for r in inventory['entries']
                                if r.get('producer') != 'local-jobs'] + job_bindings(root, host)
        validate(inventory)
        hooks = bindings(root, cards, panes, inbox, tracker, host, registry)
        return duties.preview(observe=hooks['observe'], now=now, inventory=inventory)
    from .duty_metrics import publish
    if not duties.path.exists():
        # Missing installation is explicitly UNKNOWN, not a zero-duty census.
        duties.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_json_atomic(duties.root / 'report.json', dict(
            checked_at=now, complete=False, orphaned={}, unknown=1))
        publish(root, now=now)
        return []  # Existing item findings retain their established vocabulary.
    try:
        from .duty_discovery import refresh
        refresh(root, host)
        result = duties.tick(**bindings(root, cards, panes, inbox, tracker, host, registry),
                             now=now, release=release)
    except Exception:
        write_json_atomic(duties.root / 'report.json', dict(
            checked_at=now, complete=False, orphaned={}, unknown=1))
        raise
    finally:
        publish(root, now=now)
    return result


def stop_guard(a, proceed, *, registry, panes, inbox, tracker, host):
    """The duty lock spans the stop, so tend cannot assign to a stopping agent.

    Normal self-cycles retain their duty binding. A permanent stop must name
    its explicit repool intent; external consumers get a repair item, never a
    claimed live rebind. No stopping another pane is done by this module.
    """
    duties = Duties(a.root)
    if not duties.path.exists() or getattr(a, '_cycle_internal_stop', False):
        return proceed()
    from .duty_discovery import refresh
    refresh(a.root, host)
    with duties.locked():
        data = duties.load()
        cards_list = registry.all().exact()
        cards = {card.name: card for card in cards_list}
        if len(cards) != len(cards_list) or not host:
            raise ValueError('stop duty census UNKNOWN')
        card = cards.get(a.agent)
        if card is None or card.host != host:
            raise ValueError('stop duty owner not scoped to this host')
        hooks = bindings(a.root, cards, panes, inbox, tracker, host, registry)
        held = [row for row in data['entries'] if row['holder'] == a.agent]
        projection = getattr(tracker, 'stranded_rows', None)
        if not callable(projection):
            raise ValueError('stop work census unsupported')
        from .stranded_work import eligible
        work = [r for r in projection([a.agent]) if eligible(r, operator_stopped=True)]
        # Listing is part of the stop contract, including a dry run.
        for row in held:
            print(f'  duty {row["id"]}: {row["kind"]} ({row["binding"]})')
        for row in work:
            print(f'  item {row["id"]}: {row["status"]}')
        if not held and not work:
            return proceed()
        if not getattr(a, 'repool_work', False):
            raise ValueError('stop holds work/duties; hand off first or use --repool-work')
        if getattr(a, 'after_turn', False):
            raise ValueError('repool at the completed turn boundary, not while its writer is still running')
        if a.dry_run:
            print('  would repool listed items and route listed duties before stop')
            return proceed()
        from .stranded_adapter import checkpoint
        card = cards.get(a.agent)
        preserved = checkpoint(card)
        if work and (not preserved or not all(preserved.get(k) for k in
                                              ('worktree', 'branch', 'head', 'checkpoint'))):
            raise ValueError('stop work checkpoint preservation UNKNOWN')
        for row in work:
            current = tracker.stranded_read(row['id'])
            if (current.get('assignee') != row.get('assignee')
                    or current.get('status') != row.get('status')
                    or not eligible(current, operator_stopped=True)):
                raise ValueError('stop item changed; no stop')
            comment = json.dumps(dict(original_owner=a.agent,
                reason='explicit stop --repool-work', **preserved), sort_keys=True)
            outcome = tracker.release_stranded(current, comment, operator_stopped=True)
            if outcome != 'released':
                raise ValueError('stop item release not verified; no stop')
        after = deepcopy(data)
        for row in held:
            candidates = [n for n in row.get('candidates', [])
                          if n != a.agent and n not in row.get('authors', []) and hooks['live'](n)]
            if row['binding'] == 'registry' and candidates:
                next(r for r in after['entries'] if r['id'] == row['id'])['holder'] = candidates[0]
                continue
            target = hooks['administrator']()
            if target == a.agent or not hooks['live'](target):
                raise ValueError('stop duty administrator not live; no stop')
            key = 'stranded-duty:' + hashlib.sha256(row['id'].encode()).hexdigest()
            payload = {k: row[k] for k in ('id', 'kind', 'holder', 'source')}
            repair = hooks['ensure_issue'](payload, target, key)
            hooks['notify'](target, f'{key} ERROR duty {row["id"]}; '
                            f'repair {repair}; binding needs its normal repair lane.', key)
            print(f'  duty {row["id"]}: repair {repair}; external binding still requires its normal lane')
        if after != data:
            duties._save_registry(data, after)
        return proceed()


def guard_cli(a, proceed):
    """Lazy composition keeps deployments without the registry compatible."""
    if (not Duties(a.root).path.exists()
            or getattr(a, '_cycle_internal_stop', False)):
        return proceed()
    from . import cli
    from .deployment import local_host
    registry, panes = cli._registry(a), cli._panes(a)
    card = registry.get(a.agent)
    if card.pane and panes.exists(card.pane):
        refusal = cli._foreign_session_refusal(a, a.agent, card.pane, panes)
        if refusal:
            raise ValueError(refusal)
    return stop_guard(a, proceed, registry=registry, panes=panes,
                      inbox=cli._inbox(a), tracker=cli._tracker(a), host=local_host(a.root))
