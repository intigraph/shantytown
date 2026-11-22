"""Pure triage report validation and shadow planning (za4f.6).

This does not authenticate input. The controller must read its signed verdict
record before calling or executing anything. No launcher or executor imports
this module yet. All report text remains data, including suggested repairs.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re


ACTIONS = frozenset({'comment-item', 'file-followup', 'notify-owner'})


@dataclass(frozen=True)
class Refusal:
    reason: str


@dataclass(frozen=True)
class Validated:
    report_json: str
    jobspec_sha256: str


@dataclass(frozen=True)
class ActionIntent:
    action: str
    args_json: str
    idempotency_key: str

    @property
    def args(self) -> dict:
        return json.loads(self.args_json)


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _text(value, limit=1024):
    return isinstance(value, str) and bool(value.strip()) and len(value.encode('utf-8')) <= limit


def _spec(envelope):
    if not isinstance(envelope, dict) or set(envelope) != {'resolved', 'sha256'}:
        raise ValueError('spec-envelope')
    resolved = envelope['resolved']
    digest = hashlib.sha256(_canonical(resolved).encode()).hexdigest()
    if envelope['sha256'] != digest or not isinstance(resolved, dict):
        raise ValueError('spec-digest')
    verdicts, routes = resolved.get('verdicts'), resolved.get('on')
    if (not isinstance(verdicts, list) or not verdicts or len(verdicts) > 16
            or any(not _text(v, 64) for v in verdicts) or len(set(verdicts)) != len(verdicts)
            or not isinstance(routes, dict) or set(routes) - set(verdicts)):
        raise ValueError('spec-routes')
    for names in routes.values():
        if (not isinstance(names, list) or any(not isinstance(n, str) or n not in ACTIONS for n in names)
                or len(set(names)) != len(names)):
            raise ValueError('unknown-or-duplicate-action')
    return resolved, digest


def _validate(job, envelope, report):
    spec, digest = _spec(envelope)
    if not isinstance(report, dict) or set(report) != {'job', 'run_id', 'subject', 'verdict', 'summary', 'evidence', 'report'}:
        raise ValueError('report-envelope')
    if job != 'triage' or report['job'] != job or not _text(report['run_id'], 256):
        raise ValueError('job-binding')
    subject = report['subject']
    if (not isinstance(subject, dict) or not {'kind', 'id'} <= set(subject)
            or set(subject) - {'kind', 'id', 'head'} or subject['kind'] not in ('item', 'pr', 'alert')
            or not _text(subject['id'], 1024)
            or ('head' in subject and not re.fullmatch('[0-9a-f]{40}', str(subject['head'])))):
        raise ValueError('subject')
    if report['verdict'] not in spec['verdicts'] or not _text(report['summary'], 400):
        raise ValueError('verdict-or-summary')
    evidence = report['evidence']
    if (not isinstance(evidence, list) or len(evidence) > 64
            or any(not isinstance(e, dict) or set(e) != {'kind', 'ref'}
                   or not _text(e['kind'], 64) or not _text(e['ref'], 2048) for e in evidence)):
        raise ValueError('evidence')
    payload = report['report']
    if not isinstance(payload, dict) or set(payload) - {'incident', 'coverage', 'diagnosis', 'diagnosis_evidence', 'proposed_fix'}:
        raise ValueError('triage-payload')
    incident = payload.get('incident')
    fields = {'source', 'fingerprint', 'onset', 'service', 'host', 'carrier_item'}
    if not isinstance(incident, dict) or set(incident) != fields or any(not _text(v, 512) for v in incident.values()):
        raise ValueError('incident')
    # Preserve namespaces and their full fingerprints; never truncate one into the other.
    sizes = {'alertmanager-native': 16, 'escalation-bridge': 12}
    size = sizes.get(incident['source'])
    if size is None or not re.fullmatch('[0-9a-f]{%d}' % size, incident['fingerprint']):
        raise ValueError('incident-fingerprint')
    if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?Z', incident['onset']):
        raise ValueError('incident-onset')
    datetime.fromisoformat(incident['onset'].replace('Z', '+00:00'))
    if payload.get('coverage') not in ('complete', 'partial', 'unknown'):
        raise ValueError('coverage')
    if report['verdict'] == 'diagnosed':
        refs = payload.get('diagnosis_evidence')
        fix = payload.get('proposed_fix')
        if (payload['coverage'] != 'complete' or not _text(payload.get('diagnosis'), 4000)
                or not isinstance(refs, list) or not refs or len(refs) > 64
                or any(not isinstance(r, str) or r not in {e['ref'] for e in evidence} for r in refs)
                or not isinstance(fix, dict) or set(fix) != {'repo', 'scope', 'verification'}
                or any(not _text(v, 4000) for v in fix.values())):
            raise ValueError('unproved-diagnosis')
    serialized = _canonical(report)
    if len(serialized.encode()) > 65536:
        raise ValueError('report-size')
    return Validated(serialized, digest)


def validate(job: str, jobspec: dict, report: dict) -> Validated | Refusal:
    """Validate structure and evidence binding; authentication remains the caller's job."""
    try:
        return _validate(job, jobspec, report)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        return Refusal('invalid-report-or-spec')


def plan(validated: Validated, jobspec: dict) -> list[ActionIntent] | Refusal:
    """Return immutable data only. Revalidate to refuse forged or stale snapshots."""
    try:
        spec, digest = _spec(jobspec)
        if not isinstance(validated, Validated) or digest != validated.jobspec_sha256:
            return Refusal('spec-binding')
        report = json.loads(validated.report_json)
        again = validate(report['job'], jobspec, report)
        if not isinstance(again, Validated) or again != validated:
            return Refusal('report-binding')
        intents = []
        for action in spec['on'].get(report['verdict'], []):
            args = {'subject': report['subject'], 'summary': report['summary'],
                    'evidence': report['evidence'], 'report': report['report']}
            args_json = _canonical(args)
            key = hashlib.sha256(_canonical([report['run_id'], action, args]).encode()).hexdigest()
            intents.append(ActionIntent(action, args_json, key))
        return intents
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        return Refusal('invalid-plan-input')
