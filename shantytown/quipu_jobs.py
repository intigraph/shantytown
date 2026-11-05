"""Read declared recurring jobs from an explicitly selected Quipu graph.

No writes, schedules, shell execution or TOML fallback. The caller must retain
last-known catalogue membership to detect deletion; a fresh nonempty catalogue
alone does not prove completeness. This reader rejects empty, partial and
malformed snapshots rather than advertising a healthy empty workload.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .quipu import request_headers, resolve_server

SCHEMA = "https://schema.org/"
QUECHUA = "https://scbrown.github.io/quechua/ns#"
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
        value, is_iri, datatype = row.get('o'), row['objectIRI'], row.get('datatype')
        # Verbose Quipu wraps typed literals; projected DATATYPE remains the
        # independent term-kind witness. Never unwrap an IRI or contradictory cell.
        if isinstance(value, dict):
            if (is_iri or set(value) != {'value', 'datatype'} or
                    not isinstance(datatype, str) or value['datatype'] != datatype):
                raise JobsUnavailable("typed literal contradicts query metadata")
            value = value['value']
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
                       'repeatCount', 'endTime', 'endDate')
        if any(SCHEMA+name in schedule_props for name in unsupported):
            raise JobRefused("unsupported calendar qualifier")
        calendar = any(SCHEMA+name in schedule_props for name in ('byDay', 'startTime'))
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
        kind = CalendarDeclaredJob if calendar else DeclaredJob
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


class JobCatalogue:
    def __init__(self, graph: str, *, root=None, server=None, timeout=10):
        self.graph, self.server, self.timeout = _iri(graph), resolve_server(server, root).rstrip('/'), timeout

    def read(self) -> list[DeclaredJob]:
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
        return decode_catalogue(body)
