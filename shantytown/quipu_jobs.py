"""Read, and declare, recurring jobs in an explicitly selected Quipu graph.

The reader does no schedules, shell execution or TOML fallback. The one write,
`JobCatalogue.declare`, adds a declaration this same reader admits and then
reads it back; nothing here fires a job (Chaski does). The caller must retain
last-known catalogue membership to detect deletion; a fresh nonempty catalogue
alone does not prove completeness. This reader rejects empty, partial and
malformed snapshots rather than advertising a healthy empty workload.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .quipu import request_headers, resolve_server

SCHEMA = "https://schema.org/"
QUECHUA = "https://scbrown.github.io/quechua/ns#"  # historical read spelling
QUECHUA_CANONICAL = "https://w3id.org/intigraph/quechua/ns#"
_QUECHUA_READ_ALIASES = {QUECHUA_CANONICAL + name: QUECHUA + name
                        for name in ("sourceKind", "owner", "enabled")}
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
XSD = "http://www.w3.org/2001/XMLSchema#"
MAX_TRIPLES = 4096
MAX_BYTES = 1024 * 1024
_IRI = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>"{}|^`\\]+$')
_DURATION = re.compile(r'^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$')
WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')


class JobsUnavailable(RuntimeError):
    """No trustworthy complete catalogue was obtained. Never means no jobs."""


class JobRefused(ValueError):
    """A declaration is present but cannot be admitted by this reader."""


@dataclass(frozen=True)
class Term:
    value: str | bool | int | float
    iri: bool
    datatype: str | None = None


@dataclass(frozen=True)
class DeclaredJob:
    iri: str
    event: str
    schedule: str
    name: str
    revision: str
    owner: str
    enabled: bool
    host: str
    target: str
    interval_s: int | None
    timezone: str
    anchor_s: int


@dataclass(frozen=True)
class SingleOccurrenceDeclaredJob(DeclaredJob):
    """One startDate occurrence; never advertise an elapsed recurrence."""
    repeat_count: int


@dataclass(frozen=True)
class CalendarDeclaredJob(DeclaredJob):
    """Explicit weekly civil time; interval_s is None, never elapsed P7D."""
    weekday: int
    local_time: str


def _iri(value):
    if not isinstance(value, str) or not _IRI.fullmatch(value):
        raise JobRefused("expected an expanded absolute IRI")
    return value


def _interval(value: str) -> int:
    match = _DURATION.fullmatch(value)
    if match is None or value.endswith("T"):
        raise JobRefused("unsupported fixed interval")
    seconds = sum(int(part or 0) * scale for part, scale in
                  zip(match.groups(), (86400, 3600, 60, 1)))
    if seconds < 60:
        raise JobRefused("fixed interval must be at least sixty seconds")
    return seconds


def decode_catalogue(body: dict) -> list[DeclaredJob]:
    if (not isinstance(body, dict) or body.get('error') or
            body.get('truncated') is not False or not isinstance(body.get('rows'), list)):
        raise JobsUnavailable("catalogue response is missing, refused or truncated")
    rows = body['rows']
    if not rows or len(rows) > MAX_TRIPLES or type(body.get('count')) is not int or body['count'] != len(rows):
        raise JobsUnavailable("catalogue has no declaration control or exceeds the complete-read bound")
    facts: dict[str, dict[str, set[Term]]] = {}
    for row in rows:
        if (not isinstance(row, dict) or row.get('subjectIRI') is not True or
                type(row.get('objectIRI')) is not bool):
            raise JobsUnavailable("typed/IRI query capability missing")
        subject, predicate = _iri(row.get('s')), _iri(row.get('p'))
        predicate = _QUECHUA_READ_ALIASES.get(predicate, predicate)
        value, is_iri, datatype = row.get('o'), row['objectIRI'], row.get('datatype')
        # Verbose Quipu wraps typed literals; projected DATATYPE remains the
        # independent term-kind witness. Never unwrap an IRI or contradictory cell.
        if isinstance(value, dict):
            if (is_iri or set(value) != {'value', 'datatype'} or
                    not isinstance(datatype, str) or value['datatype'] != datatype):
                raise JobsUnavailable("typed literal contradicts query metadata")
            value = value['value']
        if predicate == SCHEMA+'repeatCount' and type(value) not in (str, int):
            raise JobRefused('repeatCount requires an integer RDF cell')
        if type(value) not in (str, bool, int, float):
            raise JobsUnavailable("unsupported query cell")
        if is_iri:
            _iri(value)
        elif not isinstance(datatype, str):
            raise JobsUnavailable("literal datatype is unknown")
        facts.setdefault(subject, {}).setdefault(predicate, set()).add(Term(value, is_iri, datatype))

    def one(subject, predicate, *, iri=False, datatype=XSD+'string'):
        terms = facts.get(subject, {}).get(predicate, set())
        if len(terms) != 1:
            raise JobRefused(f"{subject}: exactly one {predicate} required")
        term = next(iter(terms))
        if term.iri is not iri or (not iri and term.datatype != datatype):
            raise JobRefused(f"{subject}: wrong RDF term kind for {predicate}")
        if iri:
            return _iri(term.value)
        if datatype != XSD+'boolean' and (not isinstance(term.value, str) or not term.value):
            raise JobRefused(f"{subject}: nonempty literal required for {predicate}")
        return term.value

    def typed(subject, kind):
        return Term(kind, True) in facts.get(subject, {}).get(RDF_TYPE, set())

    jobs = []
    for event, properties in facts.items():
        if not typed(event, SCHEMA+'Event'):
            continue
        action = one(event, SCHEMA+'potentialAction', iri=True)
        schedule = one(event, SCHEMA+'eventSchedule', iri=True)
        if not typed(action, SCHEMA+'Action') or not typed(schedule, SCHEMA+'Schedule'):
            raise JobRefused("action or schedule lacks its explicit public type")
        if SCHEMA+'startDate' in properties or SCHEMA+'endDate' in properties:
            raise JobRefused("recurring Event bounds belong on its Schedule")
        schedule_props = facts.get(schedule, {})
        unsupported = ('byMonth', 'byMonthDay', 'byMonthWeek', 'exceptDate',
                       'endTime', 'endDate')
        if any(SCHEMA+name in schedule_props for name in unsupported):
            raise JobRefused("unsupported calendar qualifier")
        single = SCHEMA+'repeatCount' in schedule_props
        if single:
            counts = schedule_props[SCHEMA+'repeatCount']
            if (len(counts) != 1 or not all(
                    not t.iri and t.datatype == XSD+'integer' and
                    (type(t.value) is int and t.value == 1 or
                     type(t.value) is str and t.value == '1') for t in counts)):
                raise JobRefused('only explicit integer repeatCount=1 is supported')
        calendar = any(SCHEMA+name in schedule_props for name in ('byDay', 'startTime'))
        if single and calendar:
            raise JobRefused('single occurrence cannot mix calendar recurrence')
        if one(action, QUECHUA+'sourceKind') != 'declared':
            raise JobRefused("job is not an explicit declaration")
        enabled = one(action, QUECHUA+'enabled', datatype=XSD+'boolean')
        if type(enabled) is bool:
            pass
        elif isinstance(enabled, str) and enabled in ('true', 'false', '1', '0'):
            enabled = enabled in ('true', '1')
        else:
            raise JobRefused("invalid boolean lexical value")
        zone = one(schedule, SCHEMA+'scheduleTimezone')
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise JobRefused("unknown schedule timezone") from exc
        anchor = one(schedule, SCHEMA+'startDate', datatype=XSD+'dateTime')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})', anchor) or anchor.endswith('-00:00'):
            raise JobRefused("activation anchor requires whole seconds and a known offset")
        try:
            instant = datetime.fromisoformat(anchor.replace('Z', '+00:00'))
        except ValueError as exc:
            raise JobRefused("invalid activation anchor") from exc
        duration = one(schedule, SCHEMA+'repeatFrequency', datatype=XSD+'duration')
        interval = None if calendar else _interval(duration)
        calendar_fields = {}
        if calendar:
            day = one(schedule, SCHEMA+'byDay', iri=True)
            start = one(schedule, SCHEMA+'startTime', datatype=XSD+'time')
            if (duration != 'P7D' or day not in {SCHEMA+d for d in WEEKDAYS} or
                    not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]:00', start)):
                raise JobRefused("weekly calendar qualifiers require P7D, one weekday and HH:MM:00")
            weekday = WEEKDAYS.index(day[len(SCHEMA):])
            try:
                local = instant.astimezone(ZoneInfo(zone))
            except (OverflowError, OSError, ValueError) as exc:
                raise JobRefused("calendar anchor is outside supported zone bounds") from exc
            if local.weekday() != weekday or local.strftime('%H:%M:%S') != start:
                raise JobRefused("calendar anchor does not match local weekday/time in its zone")
            # A matching UTC instant alone cannot choose between two wall-time
            # occurrences. The current weekly policy refuses folds and gaps.
            naive = local.replace(tzinfo=None)
            candidates = set()
            for fold in (0, 1):
                candidate = naive.replace(tzinfo=ZoneInfo(zone), fold=fold)
                stamp = candidate.timestamp()
                if datetime.fromtimestamp(stamp, ZoneInfo(zone)).replace(tzinfo=None) == naive:
                    candidates.add(stamp)
            if len(candidates) != 1:
                raise JobRefused("ambiguous or nonexistent calendar anchor")
            interval = None
            calendar_fields = dict(weekday=weekday, local_time=start[:5])
        if single:
            interval = None
            calendar_fields = dict(repeat_count=1)
        kind = SingleOccurrenceDeclaredJob if single else CalendarDeclaredJob if calendar else DeclaredJob
        jobs.append(kind(
            action, event, schedule, one(action, SCHEMA+'name'),
            one(action, SCHEMA+'identifier'), one(action, QUECHUA+'owner'), enabled,
            one(action, SCHEMA+'location', iri=True), one(action, SCHEMA+'target', iri=True),
            interval, zone, int(instant.timestamp()), **calendar_fields))
        if jobs[-1].anchor_s < 0:
            raise JobRefused("activation anchor predates supported UTC epoch")
    if not jobs:
        raise JobsUnavailable("no typed recurring-job declaration control")
    covered_actions = {j.iri for j in jobs}
    covered_schedules = {j.schedule for j in jobs}
    if any(typed(subject, SCHEMA+"Action") and subject not in covered_actions or
           typed(subject, SCHEMA+"Schedule") and subject not in covered_schedules for subject in facts):
        raise JobRefused("orphaned job action or schedule; catalogue membership is incomplete")
    if len(covered_actions) != len(jobs) or len({(j.host, j.name) for j in jobs}) != len(jobs):
        raise JobRefused("job identity or name has conflicting occurrence declarations")
    return sorted(jobs, key=lambda job: job.iri)


# --- declaring a job (st work jobs new) --------------------------------------
#
# Adding ONE weekly job to the Mac pilot (aegis-6vf.9) took a catalogue entry, a
# per-job json, a ~7 KB shuttle config, an emitters.json entry carrying sha256s,
# a deliver.py branch, a re-hashed manifest and a chaski restart. Directive
# crew/scheduled-jobs: creating one is one command and one review. The rows are
# run through decode_catalogue BEFORE anything is written, so the writer can
# never emit a declaration the reader (and so the catalogue) would refuse.

JOB_PREFIX = "urn:shantytown:job:"
HOST_PREFIX = "urn:shantytown:host:"
INBOX_PREFIX = "urn:shantytown:inbox:"
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_AGENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


@dataclass(frozen=True)
class Declaration:
    job: DeclaredJob
    turtle: str
    body: dict          # the same rows, shaped as a complete /query answer


def parse_weekday(text: str) -> int:
    word = str(text).strip().lower()
    for i, day in enumerate(WEEKDAYS):
        if word in (day.lower(), day[:3].lower()):
            return i
    raise JobRefused(f"{text!r} is not a weekday (mon..sun)")


def _host_iri(host: str) -> str:
    if _NAME.fullmatch(host or ""):
        return HOST_PREFIX + host
    try:
        return _iri(host)
    except JobRefused:
        raise JobRefused(f"host {host!r} is neither a host name nor an absolute IRI") from None


def _duration(seconds: int) -> str:
    d, rest = divmod(seconds, 86400)
    h, rest = divmod(rest, 3600)
    m, s = divmod(rest, 60)
    clock = "".join(f"{n}{u}" for n, u in ((h, "H"), (m, "M"), (s, "S")) if n)
    return "P" + (f"{d}D" if d else "") + (f"T{clock}" if clock else "")


# Fixed activation anchor for every declaration. A Monday at UTC midnight, so
# --every slots land on whole multiples of the interval since a known instant
# and the weekly anchor is the first matching slot in its zone at or after it.
ANCHOR_EPOCH = datetime(2026, 1, 5, tzinfo=dt_timezone.utc)


def _weekly_anchor(tz: ZoneInfo, weekday: int, hhmm: str) -> datetime:
    """The first unambiguous weekly slot at or after ANCHOR_EPOCH. A slot that
    falls in a DST gap or fold that week is skipped by whole weeks, because the
    reader refuses such an anchor with only "ambiguous or nonexistent"."""
    hour, minute = int(hhmm[:2]), int(hhmm[3:])
    local = ANCHOR_EPOCH.astimezone(tz)
    day = local.date() + timedelta(days=(weekday - local.weekday()) % 7)
    for _ in range(106):
        naive = datetime(day.year, day.month, day.day, hour, minute)
        stamps = {naive.replace(tzinfo=tz, fold=f).timestamp() for f in (0, 1)}
        slot = naive.replace(tzinfo=tz)
        if (len(stamps) == 1 and slot >= ANCHOR_EPOCH and
                datetime.fromtimestamp(slot.timestamp(), tz).replace(tzinfo=None) == naive):
            return slot
        day += timedelta(days=7)
    raise JobRefused(f"{WEEKDAYS[weekday]} {hhmm} never exists unambiguously in {tz.key}")


def declare_rows(name: str, *, host: str, owner: str, zone: str, inbox: str,
                 message: str, weekly: tuple[int, str] | None = None,
                 every_s: int | None = None, enabled: bool = True) -> Declaration:
    """One inbox job's declaration: weekly civil time in `zone`, or a fixed
    interval. There is no cron form here either. The output is a pure function
    of the arguments: the `-n` dry run IS what gets written, revision included
    (an anchor taken from the clock made the reviewed Turtle differ from the
    written one)."""
    if not _NAME.fullmatch(name or ""):
        raise JobRefused(f"job name {name!r}: lowercase letters, digits, - and _ only")
    if not _AGENT.fullmatch(inbox or ""):
        raise JobRefused(f"inbox agent {inbox!r} is not an agent name")
    if not isinstance(message, str) or not message.strip():
        raise JobRefused("an inbox job needs a nonempty --message")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in message):
        # A lone surrogate (undecodable argv bytes) has no Turtle spelling, so
        # it would only surface as an unknown-outcome write error.
        raise JobRefused("--message holds an undecodable character (a lone surrogate)")
    if not isinstance(owner, str) or not owner.strip():
        raise JobRefused("a job needs an owner (--owner)")
    if (weekly is None) == (every_s is None):
        raise JobRefused("pick exactly one of --weekly or --every")
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise JobRefused(f"unknown timezone {zone!r}") from exc
    host_iri = _host_iri(host)
    if weekly is not None:
        weekday, hhmm = weekly
        if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", hhmm or ""):
            raise JobRefused(f"time {hhmm!r} must be HH:MM (24-hour)")
        anchor = _weekly_anchor(tz, weekday, hhmm).isoformat()
        duration, cadence = "P7D", f"weekly:{weekday}:{hhmm}"
    else:
        if isinstance(every_s, bool) or not isinstance(every_s, int) or every_s < 60:
            raise JobRefused("--every must be at least sixty seconds")
        anchor = ANCHOR_EPOCH.strftime("%Y-%m-%dT%H:%M:%SZ")
        duration, cadence = _duration(every_s), f"every:{every_s}"
    host_key = host if _NAME.fullmatch(host) else hashlib.sha256(host_iri.encode()).hexdigest()[:12]
    job = f"{JOB_PREFIX}{host_key}:{name}"
    event, schedule, target = job + ":event", job + ":schedule", INBOX_PREFIX + inbox
    revision = "r" + hashlib.sha256(json.dumps(
        [name, host_iri, owner, zone, cadence, anchor, target, message, enabled]
    ).encode()).hexdigest()[:16]
    S, X = SCHEMA, XSD
    triples = [(s, RDF_TYPE, S + k, True, None) for s, k in
               ((job, "Action"), (event, "Event"), (schedule, "Schedule"))]
    triples += [
        (event, S + "eventSchedule", schedule, True, None),
        (event, S + "potentialAction", job, True, None),
        (job, S + "name", name, False, X + "string"),
        (job, S + "identifier", revision, False, X + "string"),
        (job, S + "description", message, False, X + "string"),
        (job, QUECHUA_CANONICAL + "sourceKind", "declared", False, X + "string"),
        (job, QUECHUA_CANONICAL + "owner", owner, False, X + "string"),
        (job, QUECHUA_CANONICAL + "enabled", enabled, False, X + "boolean"),
        (job, S + "location", host_iri, True, None),
        (job, S + "target", target, True, None),
        (schedule, S + "repeatFrequency", duration, False, X + "duration"),
        (schedule, S + "scheduleTimezone", zone, False, X + "string"),
        (schedule, S + "startDate", anchor, False, X + "dateTime"),
    ]
    if weekly is not None:
        triples += [(schedule, S + "byDay", S + WEEKDAYS[weekly[0]], True, None),
                    (schedule, S + "startTime", weekly[1] + ":00", False, X + "time")]
    rows = [dict(s=s, p=p, o=o, subjectIRI=True, objectIRI=iri,
                 **({} if iri else {"datatype": dt})) for s, p, o, iri, dt in triples]
    body = dict(count=len(rows), rows=rows, truncated=False)
    decoded, = decode_catalogue(body)       # the reader is the writer's gate

    def term(o, iri, dt):
        if iri:
            return f"<{o}>"
        lexical = ("true" if o else "false") if isinstance(o, bool) else o
        return _turtle_string(lexical) + ("" if dt == X + "string" else f"^^<{dt}>")
    turtle = "".join(f"<{s}> <{p}> {term(o, iri, dt)} .\n" for s, p, o, iri, dt in triples)
    return Declaration(decoded, turtle, body)


def _turtle_string(lexical: str) -> str:
    """A Turtle STRING_LITERAL_QUOTE spelling of ``lexical``, ASCII-only.

    json.dumps(ensure_ascii=True) wrote an emoji as a surrogate pair
    (\\ud83d\\ude00); Turtle UCHAR forbids surrogate code points, so a weekly
    job whose message held one failed its write with an unknown outcome. Each
    non-ASCII character is spelled as one \\u or \\U escape of its own code point.
    """
    return "".join(c if ord(c) < 0x80 else
                   (f"\\u{ord(c):04X}" if ord(c) <= 0xFFFF else f"\\U{ord(c):08X}")
                   for c in json.dumps(lexical, ensure_ascii=False))


class JobCatalogue:
    def __init__(self, graph: str, *, root=None, server=None, timeout=10):
        self.graph, self.server, self.timeout = _iri(graph), resolve_server(server, root).rstrip('/'), timeout

    def read(self) -> list[DeclaredJob]:
        return decode_catalogue(self._fetch())

    def declare(self, decl: Declaration) -> DeclaredJob:
        """Write one NEW declaration and read it back. Refuses to replace an
        existing identity or name: a revision is a separate, reviewed change.
        An error after the write may follow a committed write, so the caller
        reads back before retrying rather than writing twice."""
        body = self._fetch()
        empty = (body.get('rows') == [] and body.get('count') == 0 and
                 body.get('truncated') is False and not body.get('error'))
        new = decl.job
        for job in ([] if empty else decode_catalogue(body)):
            if job.iri == new.iri or (job.host, job.name) == (new.host, new.name):
                raise JobRefused(f"{new.name} is already declared on {new.host} "
                                 f"({job.iri} revision {job.revision}); not replacing it")
        from . import quipu_auth
        try:
            headers = quipu_auth.write_headers(self.server)
        except quipu_auth.CredentialRefused as exc:
            raise JobRefused(str(exc)) from None
        req = urllib.request.Request(self.server+'/knot', data=json.dumps({
            'turtle': decl.turtle, 'graph': self.graph}).encode(),
            headers={**headers, 'X-Quipu-Client': 'st-jobs'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                out = json.loads(response.read(MAX_BYTES))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise JobsUnavailable(f"write outcome unknown ({exc}); read back before retrying") from exc
        if not isinstance(out, dict) or out.get('error'):
            # An error answer can follow a committed write: unknown, not refused.
            raise JobsUnavailable(f"quipu answered the write with an error, outcome "
                                  f"unknown: {str(out)[:200]}; read back before retrying")
        if out.get('conforms') is False:   # a SHACL refusal has no "error" key (aegis-0v97)
            issues = "; ".join(f"{i.get('path', '?')}: {i.get('message', '?')}"
                               for i in (out.get('issues') or [])[:3])
            raise JobRefused(f"quipu refused the declaration (SHACL): {issues or out}")
        # HTTP 200 alone does not prove the write: the job must read back. The
        # write may already have committed, so ANY failure from here on is an
        # unknown outcome, never "refused, nothing written": a racing writer, a
        # name conflict or a malformed neighbour makes read() raise JobRefused.
        try:
            back = [job for job in self.read() if job.iri == new.iri]
        except (JobRefused, JobsUnavailable) as exc:
            raise JobsUnavailable(f"wrote {new.iri} but could not read it back "
                                  f"({exc}); read back before retrying") from exc
        if len(back) != 1 or back[0].revision != new.revision:
            raise JobsUnavailable(f"{new.iri} revision {new.revision} did not read back")
        return back[0]

    def _fetch(self) -> dict:
        query = ('SELECT ?s ?p ?o (isIRI(?s) AS ?subjectIRI) '
                 '(isIRI(?o) AS ?objectIRI) (DATATYPE(?o) AS ?datatype) '
                 f'WHERE {{ ?s ?p ?o }} LIMIT {MAX_TRIPLES+1}')
        req = urllib.request.Request(self.server+'/query', data=json.dumps({
            'query': query, 'graph': self.graph, 'verbose': True}).encode(),
            headers={**request_headers(), 'X-Quipu-Client': 'st-jobs'})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read(MAX_BYTES+1)
            if len(raw) > MAX_BYTES:
                raise JobsUnavailable("catalogue response exceeds byte bound")
            body = json.loads(raw)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise JobsUnavailable("could not read declared job graph") from exc
        if not isinstance(body, dict):
            raise JobsUnavailable("catalogue response is not an object")
        return body
