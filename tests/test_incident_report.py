import copy
import hashlib
import json

import pytest

from shantytown.incident_report import ActionIntent, Refusal, Validated, plan, validate


def envelope(resolved=None):
    resolved = resolved or {'verdicts': ['diagnosed', 'needs-owner', 'unknown'],
                            'on': {'diagnosed': ['comment-item', 'file-followup'], 'needs-owner': ['notify-owner'], 'unknown': []}}
    wire = json.dumps(resolved, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return {'resolved': resolved, 'sha256': hashlib.sha256(wire.encode()).hexdigest()}


def report():
    return {'job': 'triage', 'run_id': 'run-1', 'subject': {'kind': 'alert', 'id': 'native-alert-1'},
            'verdict': 'diagnosed', 'summary': 'Measured scope defect', 'evidence': [{'kind': 'log', 'ref': 'receipt:1'}],
            'report': {'incident': {'source': 'alertmanager-native', 'fingerprint': '1234567890abcdef',
                       'onset': '2026-11-22T04:00:00Z', 'service': 'example', 'host': 'fixture', 'carrier_item': 'item-1'},
                       'coverage': 'complete', 'diagnosis': 'Row type differs from the declared schema',
                       'diagnosis_evidence': ['receipt:1'],
                       'proposed_fix': {'repo': 'example/project', 'scope': 'source only', 'verification': 'Repeat the row validation'}}}


def test_shadow_intents_and_stable_keys():
    spec, raw = envelope(), report()
    value = validate('triage', spec, raw)
    assert isinstance(value, Validated)
    actions = plan(value, spec)
    assert [a.action for a in actions] == ['comment-item', 'file-followup']
    assert all(isinstance(a, ActionIntent) for a in actions)
    assert len({a.idempotency_key for a in actions}) == 2
    assert plan(validate('triage', dict(reversed(list(spec.items()))), dict(reversed(list(raw.items())))), spec) == actions
    raw['run_id'] = 'run-2'
    assert plan(validate('triage', spec, raw), spec)[0].idempotency_key != actions[0].idempotency_key


def test_mutable_inputs_and_returned_args_cannot_rebind_snapshot():
    spec, raw = envelope(), report()
    value = validate('triage', spec, raw)
    before = plan(value, spec)
    raw['report']['proposed_fix']['scope'] = 'run shell now'
    before[0].args['report']['proposed_fix']['scope'] = 'changed'
    assert plan(value, spec) == before
    changed = copy.deepcopy(spec['resolved']); changed['on']['diagnosed'] = ['notify-owner']
    assert isinstance(plan(value, envelope(changed)), Refusal)


@pytest.mark.parametrize('change', [
    lambda r: r.update(job='task'), lambda r: r.update(run_id=''),
    lambda r: r.update(summary='é' * 201), lambda r: r.update(summary='\ud800'),
    lambda r: r.update(verdict='invented'), lambda r: r.update(extra=True),
    lambda r: r.update(subject={'kind': 'shell', 'id': 'x'}),
    lambda r: r['subject'].update(head='main'), lambda r: r.update(evidence=[]),
    lambda r: r['evidence'][0].update(command='execute'),
    lambda r: r['report'].update(coverage='partial'),
    lambda r: r['report'].update(coverage='unknown'),
    lambda r: r['report'].update(diagnosis_evidence=['other-receipt']),
    lambda r: r['report'].update(proposed_fix={'command': 'execute'}),
    lambda r: r['report']['incident'].update(fingerprint='1234567890ab'),
    lambda r: r['report']['incident'].update(source='unknown-source'),
    lambda r: r['report']['incident'].update(onset='2026-02-30T04:00:00Z'),
    lambda r: r['report']['incident'].update(onset='yesterday'),
    lambda r: r['report']['incident'].update(carrier_item=''),
    lambda r: r['report'].update(truncated=True),
    lambda r: r['report']['proposed_fix'].update(scope=float('nan')),
])
def test_malformed_or_unproved_reports_refuse(change):
    raw = report(); change(raw)
    assert isinstance(validate('triage', envelope(), raw), Refusal)


@pytest.mark.parametrize('names', [['shell'], ['file-followup', 'file-followup'], [None], 'file-followup'])
def test_unknown_duplicate_or_malformed_actions_refuse(names):
    spec = envelope(); spec['resolved']['on']['diagnosed'] = names
    assert isinstance(validate('triage', envelope(spec['resolved']), report()), Refusal)


def test_forged_snapshot_and_hash_refuse():
    spec = envelope(); spec['sha256'] = '0' * 64
    assert isinstance(validate('triage', spec, report()), Refusal)
    assert isinstance(plan(Validated('{}', envelope()['sha256']), envelope()), Refusal)
    assert isinstance(plan(Validated('not-json', envelope()['sha256']), envelope()), Refusal)


def test_unknown_has_no_action_and_partial_needs_owner_cannot_invent_fix():
    spec, raw = envelope(), report()
    raw['verdict'] = 'unknown'; raw['report'] = {'incident': raw['report']['incident'], 'coverage': 'unknown'}
    assert plan(validate('triage', spec, raw), spec) == []
    raw['verdict'] = 'needs-owner'
    assert [a.action for a in plan(validate('triage', spec, raw), spec)] == ['notify-owner']
    raw['report']['incident'].update(source='escalation-bridge', fingerprint='1234567890ab')
    assert isinstance(validate('triage', spec, raw), Validated)


def test_module_has_no_io_or_lifecycle_imports():
    import ast
    from pathlib import Path
    tree = ast.parse(Path('shantytown/incident_report.py').read_text())
    imports = {n.module if isinstance(n, ast.ImportFrom) else n.names[0].name
               for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert imports == {'dataclasses', 'datetime', 'hashlib', 'json', 're'}
