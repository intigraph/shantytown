"""Capacity boundary for deployment-selected SDK producers.

Invoked with the installed st interpreter by the neutral tracker selector. JSON
on stdin carries only the selected binary/options and SDK argument vector; all
credentials stay in the inherited environment. No write retry is performed.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from .plate_capacity import assignment_lock, ensure_room, ensure_update_room, active, PlateFull
from .sd import SdTracker


BOOLEANS = {'--json', '--robot', '--quiet', '-q', '--ephemeral', '--dry-run',
            '--silent', '--force', '--credential-admission'}
VALUES = set(('title format type actor priority description body store quipu status defer '
              'graph at description-file assignee agent-name harness owner acceptance-criteria '
              'acceptance model external-ref session due estimate labels set-labels parent '
              'agent-context slug deps workflow-run step visit notes design check-acceptance '
              'uncheck-acceptance add-acceptance if-revision rank before after add-label '
              'remove-label transition-comment').split())
SHORT = {'-a':'--assignee', '-s':'--status', '-d':'--description', '-t':'--type',
         '-p':'--priority', '-e':'--estimate', '-l':'--labels'}


def fields(arguments):
    """Parse option positions, never interpret literal description/body values.

    Unknown/new SDK switches refuse rather than silently bypassing admission.
    Bulk and claim need their own atomic backend contract and are not producers.
    """
    i = 2
    while i < len(arguments):
        word = arguments[i]
        if word in BOOLEANS:
            i += 1
            continue
        name, equal, value = word.partition('=')
        if not equal and len(word) > 2 and word[:2] in SHORT:
            name, equal, value = SHORT[word[:2]], '=', word[2:]
        name = SHORT.get(name, name)
        if not name.startswith('--') or name[2:] not in VALUES:
            raise ValueError('unsupported producer option; no unguarded assignment')
        width = 1 if equal else 2
        if not equal:
            if i + 1 >= len(arguments):
                raise ValueError('missing producer option value')
            value = arguments[i+1]
        yield name, value, i, width
        i += width


def option(arguments, name, short=None):
    found = [value for flag,value,_,_ in fields(arguments) if flag == name]
    if len(found) > 1:
        raise ValueError('ambiguous repeated assignment option')
    return found[0] if found else None


def without(arguments, name):
    removed = {i+j for flag,_,i,width in fields(arguments) if flag == name for j in range(width)}
    return [v for i,v in enumerate(arguments) if i not in removed]


def proposed_fields(arguments, previous):
    """Project only fields that change capacity membership; keep argv intact."""
    candidate = previous.copy()
    for flag, key in (('--title', 'title'), ('--status', 'status'), ('--defer', 'defer_until')):
        value = option(arguments, flag)
        if value is not None:
            candidate[key] = value
    parsed = list(fields(arguments))
    replacements = [value for flag, value, _, _ in parsed if flag in ('--labels', '--set-labels')]
    labels = candidate.get('labels') or []
    if isinstance(labels, str):
        labels = labels.split(',')
    labels = {v.get('name', '') if isinstance(v, dict) else v for v in labels}
    if replacements:
        labels = {label.strip() for value in replacements for label in value.split(',') if label.strip()}
    added = {value.strip() for flag, value, _, _ in parsed if flag == '--add-label'}
    removed = {value.strip() for flag, value, _, _ in parsed if flag == '--remove-label'}
    if any(',' in value for value in added | removed) or added & removed:
        raise ValueError('ambiguous producer label mutation; no unguarded write')
    candidate['labels'] = sorted((labels | added) - removed)
    return candidate


def run(arguments, tracker, execute, notify):
    """One SDK write under the same owner lock used by go/task/automatic work."""
    if not arguments or arguments[0] not in ('create', 'update'):
        raise ValueError('producer capacity supports create/update only')
    owner = option(arguments, '--assignee', '-a')
    current = None
    if arguments[0] == 'create':
        if len(arguments) < 2 or arguments[1].startswith('-'):
            raise ValueError('producer create requires title')
        candidate = proposed_fields(arguments, {'title': arguments[1], 'labels': [],
                                               'assignee': owner, 'status': 'open'})
        if option(arguments, '--defer'):
            candidate['status'] = 'deferred'
    else:
        if len(arguments) < 2:
            raise ValueError('producer update requires exact ID')
        current = tracker.get(arguments[1])
        owner = owner if owner is not None else current.assignee
        candidate = proposed_fields(arguments, vars(current))
    if not owner:
        return execute(arguments)
    with assignment_lock(tracker, owner):
        if current is not None:
            previous = current
            current = tracker.get(current.id)
            if current.assignee != previous.assignee:
                raise ValueError('producer owner changed during admission')
            candidate = proposed_fields(arguments, vars(current))
        if not active(candidate | {'assignee': owner}, owner):
            return execute(arguments)
        full = False
        try:
            if current is None:
                ensure_room(tracker, owner)
            else:
                ensure_update_room(tracker, owner, current, candidate | {'assignee': owner})
        except PlateFull:
            if current is not None and current.assignee:
                raise
            arguments = without(arguments, '--assignee')
            if current is not None:
                arguments = without(arguments, '--status') + ['--status', 'open']
            full = True
        result = execute(arguments)  # exactly once; errors remain indeterminate
        if full and result.returncode == 0:
            try:
                value = json.loads(result.stdout)
                if isinstance(value, list) and len(value) == 1:
                    value = value[0]
                item_id = value['id']
                notify(owner, item_id)
            except Exception as error:
                print('capacity: work retained in pool; lead notice UNKNOWN: '
                      + type(error).__name__, file=sys.stderr)
        return result


def main():
    value = json.load(sys.stdin)
    binary, options, arguments = value['binary'], value['options'], value['arguments']
    if (not isinstance(binary, str) or not Path(binary).is_absolute()
            or not all(isinstance(v, str) for v in options + arguments)):
        raise ValueError('invalid selected SDK transport')
    def execute(args):
        return subprocess.run([binary, *options, *args], capture_output=True,
                              text=True, timeout=value['timeout'])
    # All reads and the final mutation use the parent's SAME selected SDK route.
    import os
    tracker = SdTracker(store=os.environ.get('SHANTY_SD_STORE'),
                        quipu=os.environ.get('SHANTY_SD_QUIPU'),
                        prefix=os.environ.get('SHANTY_SD_PREFIX'))
    tracker._bd = lambda *args: execute(list(args))
    def notify(owner, item_id):
        from .files import FilesRegistry
        import os
        registry = FilesRegistry(Path(os.environ['SHANTY_ROOT']) / 'crew')
        lead = registry.get(owner).reports_to
        if not lead:
            raise ValueError('owner has no lead')
        result = execute(['create', f'inbox: capacity: {item_id} retained in pool; {owner} full',
                          '--assignee', lead, '--labels', 'inbox', '--json'])
        if result.returncode:
            raise ValueError('lead delivery unproven')
    result = run(arguments, tracker, execute, notify)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('producer assignment UNKNOWN: ' + type(error).__name__, file=sys.stderr)
        raise SystemExit(2)
