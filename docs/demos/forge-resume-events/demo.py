"""Offline source replay; no forge request or tracker mutation."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import deferrals, deferral_waits, resume_kinds
from shantytown import resume_forge_events

BASE = 'f9941a35a914ec925a8d2226aade3dcb79b124b8'
old = ModuleType('baseline_resume_kinds')
old.__package__ = 'shantytown'
source = subprocess.check_output(['git', 'show', BASE + ':shantytown/resume_kinds.py'], text=True)
exec(compile(source, 'baseline_resume_kinds.py', 'exec'), old.__dict__)
arg = 'github/example/project#123'
for label, implementation in [('before', old), ('after', resume_kinds)]:
    try:
        implementation.validate('pr-merged', arg)
        print(label + ': exact PR marker ACCEPTED')
    except ValueError:
        print(label + ': exact PR marker REFUSED')
for merged, state, label in [(False, 'closed', 'closed unmerged'), (True, 'closed', 'merged')]:
    met, why = resume_forge_events.evaluate('pr-merged', arg, read=lambda *a: dict(
        number=123, merged=merged, state=state, merged_at='2026-11-06T03:00:00Z'))
    print(f'{label}: met={met}; {why}')
met, why = resume_forge_events.evaluate('pr-merged', arg,
    read=lambda *a: (_ for _ in ()).throw(OSError()))
print(f'failed read: met={met}; {why}')
now = datetime(2026, 11, 6, 4, tzinfo=timezone.utc)
for hours in (1, 24):
    try:
        deferral_waits.validate('', '', deferrals.Condition('pr-merged', arg),
                                now + timedelta(hours=hours), now, window=True)
        print(f'{hours}h backstop: ACCEPTED')
    except ValueError:
        print(f'{hours}h backstop: REFUSED even with window=True')

# Controller evidence is a typed comment, not an authority claim in free prose.
from types import SimpleNamespace
from shantytown import deferral_notes, resume_rulings
from shantytown.answer import Answer
from shantytown.protocols import Agent
crew = [Agent('admin', role='administrator'), Agent('lead', role='lead'),
        Agent('worker', reports_to='lead')]
registry = SimpleNamespace(all=lambda: Answer.complete_read(crew, how='offline fixture'))
until = '2026-11-07T04:00:00Z'
waiting = dict(id='example-123', defer_until=until,
    notes=deferral_notes.provenance('worker', '2026-11-06T03:00:00Z', until))
marker = ('resume-event-v1: activation:example-123 outcome=granted '
          'authority=admin at=2026-11-06T03:01:00Z')
row = dict(id=1, author='admin', created_at='2026-11-06T03:01:01Z', text=marker)
for label, evidence in [('free prose', [row | {'text': 'approved, go ahead'}]),
                        ('typed administrator grant', [row]),
                        ('spoofed author', [row | {'author': 'worker'}]),
                        ('newer revocation', [row, dict(id=2, author='lead',
                            created_at='2026-11-06T03:02:01Z',
                            text='resume-event-v1: activation:example-123 outcome=revoked authority=lead at=2026-11-06T03:02:00Z')])]:
    met, why = resume_rulings.evaluate('activation', 'example-123', waiting, now,
        show=lambda item: dict(id=item, assignee='worker'),
        comments=lambda item: evidence, registry=registry)
    print(f'{label}: met={met}; {why}')
