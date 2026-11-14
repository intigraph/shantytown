"""Offline replay: use the actual undefer method at base and in this checkout."""
import ast
import json
from pathlib import Path
import subprocess
import textwrap
from types import SimpleNamespace

from shantytown.feed_check import dispatchable, hauls
from shantytown.sd import SdTracker

BASE = 'c96be285f052ae5ec709137842240bea0b887ce1'

def method(source):
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TrackerAdapter')
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'undefer')
    scope = {}
    exec(textwrap.dedent(ast.get_source_segment(source, node)), scope)
    return scope['undefer']

root = Path(__file__).resolve().parents[3]
base = subprocess.check_output(['git', 'show', BASE + ':shantytown/feed_check.py'], cwd=root, text=True)
head = (root / 'shantytown/feed_check.py').read_text()
for label, source in [('BASE', base), ('CANDIDATE', head)]:
    for priority in [1, 0]:
        resumed = dict(id='resumed', title='Resumed item', priority=priority, status='deferred',
                       assignee='worker', created_at='2026-01-01T00:00:00Z')
        other = dict(id='ready', title='Ready item', priority=1-priority, status='open',
                     assignee='', created_at='2026-01-01T00:00:00Z')
        adapter = SimpleNamespace(tracker=SimpleNamespace(update=lambda item, **fields: resumed.update(fields)))
        method(source)(adapter, 'resumed')
        rows = SdTracker._tend_order([resumed, other])
        print(json.dumps(dict(revision=label, resumed_priority=priority, owner=resumed['assignee'],
                             haul=hauls(rows), ranked_pool=[i for i, _ in dispatchable({'worker'}, rows)])))
        if label == 'CANDIDATE':
            assert not resumed['assignee'] and not hauls(rows)
            assert dispatchable({'worker'}, rows)[0][0] == ('ready' if priority else 'resumed')
