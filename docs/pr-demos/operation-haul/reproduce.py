"""Read-only library probe; base functions come from the exact committed source."""
import ast
import copy
import json
import subprocess

from shantytown import feed_check, stop_event

BASE = '6bb4694988539c60fbc1a4060a9ecb75fe9c8bcf'


def original(module, name):
    text = subprocess.check_output(['git', 'show', f'{BASE}:shantytown/{module.__name__.split(".")[-1]}.py'], text=True)
    tree = ast.parse(text)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = vars(module).copy()
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<committed-base>', 'exec'), namespace)
    return namespace[name]


operation = {'id': 'op-1', 'title': 'Prepared rollout', 'assignee': 'worker',
             'labels': ['deploy-operation'], 'status': 'open'}
ordinary = {'id': 'work-1', 'title': 'Repair docs', 'assignee': 'worker', 'status': 'open'}
print('Synthetic records; no tracker, pane, deployment or network mutation.')
print('Base:', BASE)
for label, haul, assigned in [('before', original(feed_check, 'hauls'), original(stop_event, '_assigned_to')),
                               ('after', feed_check.hauls, stop_event._assigned_to)]:
    rows = copy.deepcopy([operation, ordinary])
    print(label, json.dumps({'queue': haul(rows), 'resume_ids': [r['id'] for r in assigned('worker', rows)]}, sort_keys=True))
    assert rows == [operation, ordinary]
print('Ordinary work retained; operation state unchanged.')
