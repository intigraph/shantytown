"""Read-only synthetic library demo; run against base and candidate PYTHONPATH."""
from dataclasses import replace
from types import SimpleNamespace

from shantytown.governor import Reading, Verdict

verdict = Verdict(reading=Reading(source='none'))
implemented = hasattr(verdict, 'admit_class')
if implemented:
    verdict = replace(verdict, admit_class=True)
print('Class filter:', 'enabled explicitly' if implemented else 'not implemented')
for labels in ([], ['work:design'], ['work:important-quipu-code']):
    item = SimpleNamespace(id='synthetic-job', priority=1, labels=labels)
    for lane in ('claude', 'codex'):
        current = replace(verdict, work_harness=lane) if implemented else verdict
        reason = current.admits(item, 'synthetic-worker')
        print(f'labels={labels!r}; target={lane}: {reason or "ADMITTED"}')
