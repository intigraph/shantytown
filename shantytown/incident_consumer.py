"""Shadow consumer for signed triage reports (za4f.6.1, step H1).

Takes one triage report record that the SIGNED READER has already verified,
binds it to the frozen launch input, runs the pure validator and planner of
`incident_report`, and records the planned intents ONCE in a private journal.
It executes nothing: no launcher, signer, executor, queue or network import.
The journal is the input of the next step (H2), not an action.

Authentication stays the caller's job. `verified` must be exactly True, set by
the code that read the record from `st-gate-verdicts` and checked its signature;
anything else refuses before any parsing. `verified` vouches for the RECORD only.
`frozen` and `jobspec` are trusted launch state and must come from the caller (the
launcher's own copy), never from the event: an event that carried its own frozen
input and a self-consistent jobspec would attest its own incident binding and
routes. `consume_event` therefore takes them as arguments and refuses an event
whose embedded copies differ (`launch-mismatch`). A report that passes here is
still untrusted data (see docs/alert-triage-job.md).

Refusals are recorded, not dropped: once the journal directory is known safe,
every refusal writes a `refusal-<key>.json` record (digests and reason only, never
the untrusted record itself) so an ignored alert leaves evidence. Only an unsafe
journal directory refuses without a record, because there is nowhere safe to write.
Refusals are keyed by (reason, record, frozen, jobspec): the same record refused under
two different specs leaves two records.

A journal write that fails (ENOSPC, EIO, EXDEV from os.link or fsync) is FATAL: the
OSError propagates to the caller. Raising is the loud form; returning a Refusal here
would be the silent drop this module exists to prevent. The event source must treat
the exception as not-consumed and redeliver. A fault before the link journals nothing,
not even a refusal, since the journal is the thing that failed; the redelivery is
consumed normally, once. A fault in the directory fsync AFTER the link has succeeded
leaves the record in place (possibly not yet durable) and still raises; the
redelivery then finds it and returns replay=True with the same intents.

Each distinct refused record or garbage event writes its own refusal file, so the
journal is unbounded under hostile input. Accepted for H1 shadow; H2 must bound it.

Known limits, accepted for H1: the directory check is lstat-then-use, so a
caller that swaps its own private directory between check and write races
itself; and a crash between mkstemp and unlink leaves a `.pending-*` file that
nothing reads (H2's reader must ignore dot-files).
"""
from dataclasses import dataclass
import hashlib
import json
import os
import re
import stat
import tempfile

from shantytown.incident_report import ActionIntent, Refusal, plan, validate

FROZEN_KEYS = frozenset({'version', 'item', 'fingerprint_kind', 'fingerprint', 'onset_utc'})
EVENT_KEYS = frozenset({'kind', 'record', 'frozen', 'jobspec'})
JOURNAL_VERSION = 1
# The replay read was capped at 1 MiB while the write was not, so an oversized
# plan journaled fine and then refused on every replay. Both sides share one cap.
RECORD_CAP = 1 << 20


@dataclass(frozen=True)
class Consumed:
    run_id: str
    intents: tuple
    replay: bool
    journal_path: str


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _digest(value) -> str:
    """SHA256 of the canonical form; a value JSON cannot carry is digested by repr, marked.

    Too deep to serialize or repr (both recurse and raise RecursionError): digested by
    type name only. Such values then share one key, which collapses their refusal
    records into one; that is a lost distinction, not a lost refusal.
    """
    try:
        wire = _canonical(value)
    except (TypeError, ValueError, RecursionError):
        try:
            wire = 'unserializable:' + repr(value)
        except RecursionError:
            wire = 'unrepresentable:' + type(value).__name__
    return hashlib.sha256(wire.encode()).hexdigest()


def _frozen_ok(frozen) -> bool:
    return (isinstance(frozen, dict) and set(frozen) == FROZEN_KEYS and frozen['version'] == 1
            and all(isinstance(frozen[k], str) and frozen[k] for k in FROZEN_KEYS - {'version'}))


_ONSET = re.compile(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z')


def _onset_key(text):
    """04:00:00Z and 04:00:00.000Z both pass the validator; they are one instant.

    Compared as (seconds, fraction without trailing zeros) rather than through
    datetime, which truncates past microseconds and would equate distinct onsets.
    """
    match = _ONSET.fullmatch(text) if isinstance(text, str) else None
    return None if match is None else (match.group(1), (match.group(2) or '').rstrip('0'))


def _same_onset(reported, frozen) -> bool:
    left = _onset_key(reported)
    return left is not None and left == _onset_key(frozen)


def _journal_dir_ok(path: str) -> bool:
    """A real directory (not a link), owned by us, not writable by anyone else."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


def _create_once(journal: str, name: str, body: bytes) -> bool:
    """Durably create journal/name with body; False when it already exists.

    fsync before the link and of the directory after it: without them a crash could
    leave a linked but empty record that every replay then refuses as unreadable.
    """
    # Any OSError below propagates (see the module docstring: journal faults are fatal);
    # the finally still removes the temp file so a failed write leaves no `.pending-*`.
    fd, tmp = tempfile.mkstemp(dir=journal, prefix='.pending-')
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, os.path.join(journal, name))  # exclusive: exactly one writer creates it
            created = True
        except FileExistsError:
            created = False
    finally:
        os.unlink(tmp)
    dir_fd = os.open(journal, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    return created


def _refuse(journal: str, reason: str, record, frozen, jobspec, extra=None) -> Refusal:
    """Record the refusal once, keyed by (reason, record, frozen, jobspec, extra), and return it."""
    entry = {'version': JOURNAL_VERSION, 'kind': 'refusal', 'reason': reason,
             'record_sha256': _digest(record), 'frozen_sha256': _digest(frozen),
             'jobspec_sha256': _digest(jobspec), **(extra or {})}
    run_id = record.get('run_id') if isinstance(record, dict) else None
    if isinstance(run_id, str) and len(run_id) <= 1024:
        entry['run_id'] = run_id
    body = (_canonical(entry) + '\n').encode()
    _create_once(journal, 'refusal-' + _digest(entry) + '.json', body)
    return Refusal(reason)


def _record(report: dict, validated, intents) -> dict:
    return {'version': JOURNAL_VERSION, 'run_id': report['run_id'],
            'report_sha256': hashlib.sha256(validated.report_json.encode()).hexdigest(),
            'jobspec_sha256': validated.jobspec_sha256,
            'intents': [{'action': i.action, 'idempotency_key': i.idempotency_key, 'args_json': i.args_json}
                        for i in intents]}


def consume(record, *, frozen, jobspec, journal: str, verified) -> Consumed | Refusal:
    """Return the planned shadow intents for one verified report, journaled once."""
    if not _journal_dir_ok(journal):
        return Refusal('journal-dir')
    if verified is not True:
        return _refuse(journal, 'unverified-record', record, frozen, jobspec)
    if not _frozen_ok(frozen):
        return _refuse(journal, 'frozen-input', record, frozen, jobspec)
    validated = validate('triage', jobspec, record)
    if isinstance(validated, Refusal):
        return _refuse(journal, validated.reason, record, frozen, jobspec)
    report = json.loads(validated.report_json)
    incident = report['report']['incident']
    # The report must be about THIS incident, not merely a well-formed one.
    if (incident['source'] != frozen['fingerprint_kind'] or incident['fingerprint'] != frozen['fingerprint']
            or not _same_onset(incident['onset'], frozen['onset_utc']) or incident['carrier_item'] != frozen['item']):
        return _refuse(journal, 'incident-binding', record, frozen, jobspec)
    intents = plan(validated, jobspec)
    if isinstance(intents, Refusal):
        return _refuse(journal, intents.reason, record, frozen, jobspec)
    wanted = _record(report, validated, intents)
    body = (_canonical(wanted) + '\n').encode()
    if len(body) > RECORD_CAP:
        return _refuse(journal, 'record-too-large', record, frozen, jobspec)
    final = os.path.join(journal, hashlib.sha256(report['run_id'].encode()).hexdigest() + '.json')
    replay = not _create_once(journal, os.path.basename(final), body)
    if replay:
        try:
            with open(final, 'rb') as handle:
                existing = json.loads(handle.read(RECORD_CAP + 1))
        except (OSError, ValueError):
            return _refuse(journal, 'journal-unreadable', record, frozen, jobspec)
        if existing != wanted:
            return _refuse(journal, 'run-rebound', record, frozen, jobspec)
    return Consumed(report['run_id'], tuple(intents), replay, final)


def consume_event(raw: bytes, *, frozen, jobspec, journal: str, verified) -> Consumed | Refusal:
    """Consume one serialized incident_report event: {kind, record, frozen, jobspec}.

    This is the replayable wire form: a recorded event file fed twice is one intent
    record. A malformed event is refused AND recorded, keyed by the digest of its bytes.
    `frozen` and `jobspec` are the caller's trusted launch state; the event's copies are
    provenance only and must equal them exactly, or the event is refused as
    `launch-mismatch`. The trusted copies, never the event's, are what get validated.
    """
    if not _journal_dir_ok(journal):
        return Refusal('journal-dir')
    event = None
    if isinstance(raw, (bytes, bytearray)) and len(raw) <= RECORD_CAP:
        try:
            event = json.loads(raw)
        # json.loads raises RecursionError, not ValueError, on deep nesting (b"[" * 200000
        # is 200 KB, under the cap). Uncaught, it read as "not consumed, redeliver": a
        # poison event that was never recorded.
        except (ValueError, RecursionError):
            event = None
    if not (isinstance(event, dict) and set(event) == EVENT_KEYS and event['kind'] == 'incident_report'):
        marker = {'unparsed_event_sha256': hashlib.sha256(bytes(raw) if isinstance(raw, (bytes, bytearray))
                                                         else repr(raw).encode()).hexdigest()}
        return _refuse(journal, 'event-shape', marker, frozen, jobspec)
    if _digest(event['frozen']) != _digest(frozen) or _digest(event['jobspec']) != _digest(jobspec):
        # The event's own copies are digested into the entry so that two different
        # forged specs against one record leave two records, not one.
        return _refuse(journal, 'launch-mismatch', event['record'], frozen, jobspec,
                       {'event_frozen_sha256': _digest(event['frozen']),
                        'event_jobspec_sha256': _digest(event['jobspec'])})
    return consume(event['record'], frozen=frozen, jobspec=jobspec, journal=journal, verified=verified)


__all__ = ['Consumed', 'consume', 'consume_event', 'ActionIntent', 'Refusal']
