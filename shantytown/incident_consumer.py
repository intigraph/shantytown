"""Shadow consumer for signed triage reports (za4f.6.1, step H1).

Takes one triage report record that the SIGNED READER has already verified,
binds it to the frozen launch input, runs the pure validator and planner of
`incident_report`, and records the planned intents ONCE in a private journal.
It executes nothing: no launcher, signer, executor, queue or network import.
The journal is the input of the next step (H2), not an action.

Authentication stays the caller's job. `verified` must be exactly True, set by
the code that read the record from `st-gate-verdicts` and checked its signature;
anything else refuses before any parsing. A report that passes here is still
untrusted data (see docs/alert-triage-job.md).
"""
from dataclasses import dataclass
import hashlib
import json
import os
import stat
import tempfile

from shantytown.incident_report import ActionIntent, Refusal, plan, validate

FROZEN_KEYS = frozenset({'version', 'item', 'fingerprint_kind', 'fingerprint', 'onset_utc'})
JOURNAL_VERSION = 1


@dataclass(frozen=True)
class Consumed:
    run_id: str
    intents: tuple
    replay: bool
    journal_path: str


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _frozen_ok(frozen) -> bool:
    return (isinstance(frozen, dict) and set(frozen) == FROZEN_KEYS and frozen['version'] == 1
            and all(isinstance(frozen[k], str) and frozen[k] for k in FROZEN_KEYS - {'version'}))


def _journal_dir_ok(path: str) -> bool:
    """A real directory (not a link), owned by us, not writable by anyone else."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


def _record(report: dict, validated, intents) -> dict:
    return {'version': JOURNAL_VERSION, 'run_id': report['run_id'],
            'report_sha256': hashlib.sha256(validated.report_json.encode()).hexdigest(),
            'jobspec_sha256': validated.jobspec_sha256,
            'intents': [{'action': i.action, 'idempotency_key': i.idempotency_key, 'args_json': i.args_json}
                        for i in intents]}


def consume(record, *, frozen, jobspec, journal: str, verified) -> Consumed | Refusal:
    """Return the planned shadow intents for one verified report, journaled once."""
    if verified is not True:
        return Refusal('unverified-record')
    if not _frozen_ok(frozen):
        return Refusal('frozen-input')
    if not _journal_dir_ok(journal):
        return Refusal('journal-dir')
    validated = validate('triage', jobspec, record)
    if isinstance(validated, Refusal):
        return validated
    incident = json.loads(validated.report_json)['report']['incident']
    # The report must be about THIS incident, not merely a well-formed one.
    if (incident['source'] != frozen['fingerprint_kind'] or incident['fingerprint'] != frozen['fingerprint']
            or incident['onset'] != frozen['onset_utc'] or incident['carrier_item'] != frozen['item']):
        return Refusal('incident-binding')
    intents = plan(validated, jobspec)
    if isinstance(intents, Refusal):
        return intents
    report = json.loads(validated.report_json)
    wanted = _record(report, validated, intents)
    name = hashlib.sha256(report['run_id'].encode()).hexdigest() + '.json'
    final = os.path.join(journal, name)
    body = (_canonical(wanted) + '\n').encode()
    fd, tmp = tempfile.mkstemp(dir=journal, prefix='.pending-')
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(body)
        try:
            os.link(tmp, final)  # exclusive: exactly one writer creates the run's record
            replay = False
        except FileExistsError:
            replay = True
    finally:
        os.unlink(tmp)
    if replay:
        try:
            with open(final, 'rb') as handle:
                existing = json.loads(handle.read(1 << 20))
        except (OSError, ValueError):
            return Refusal('journal-unreadable')
        if existing != wanted:
            return Refusal('run-rebound')
    return Consumed(report['run_id'], tuple(intents), replay, final)


__all__ = ['Consumed', 'consume', 'ActionIntent', 'Refusal']
