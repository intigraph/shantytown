"""Run from the repository root; private fixture, no execution or network."""
import json
from pathlib import Path
from shantytown.incident_report import Refusal, plan, validate

x = json.loads(Path(__file__).with_name('input.json').read_text())
spec, report = x['jobspec'], x['report']
value = validate('triage', spec, report)
actions = plan(value, spec)
print(json.dumps({'complete_diagnosis': [a.action for a in actions], 'shadow_only': True}))
report['report']['coverage'] = 'partial'
print(json.dumps({'partial_diagnosis_refused': isinstance(validate('triage', spec, report), Refusal)}))
report['verdict'] = 'unknown'
print(json.dumps({'unknown_intents': len(plan(validate('triage', spec, report), spec))}))
print(json.dumps({'original_snapshot_unchanged': plan(value, spec) == actions}))
