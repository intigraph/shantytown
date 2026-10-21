"""Before/after typed calendar read; synthetic RDF rows, no server or writes."""
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import types

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE))
from shantytown import quipu_jobs as current


def snapshot(calendar):
    rows = []
    def fact(s, p, o, iri=False, datatype=current.XSD+'string'):
        row = dict(s='urn:example:'+s, p=p, o=o, subjectIRI=True, objectIRI=iri)
        if not iri:
            row['datatype'] = datatype
        rows.append(row)
    for name, kind in (('job', 'Action'), ('event', 'Event'), ('schedule', 'Schedule')):
        fact(name, current.RDF_TYPE, current.SCHEMA+kind, True)
    fact('event', current.SCHEMA+'potentialAction', 'urn:example:job', True)
    fact('event', current.SCHEMA+'eventSchedule', 'urn:example:schedule', True)
    for key, value in (('name', 'weekly-fixture'), ('identifier', 'r1')):
        fact('job', current.SCHEMA+key, value)
    for key, value in (('sourceKind', 'declared'), ('owner', 'operator')):
        fact('job', current.QUECHUA+key, value)
    fact('job', current.QUECHUA+'enabled', False, datatype=current.XSD+'boolean')
    for key in ('location', 'target'):
        fact('job', current.SCHEMA+key, 'urn:example:'+key, True)
    fact('schedule', current.SCHEMA+'repeatFrequency', 'P7D', datatype=current.XSD+'duration')
    fact('schedule', current.SCHEMA+'scheduleTimezone', 'America/New_York')
    fact('schedule', current.SCHEMA+'startDate', '2026-10-26T09:17:00-04:00',
         datatype=current.XSD+'dateTime')
    if calendar:
        fact('schedule', current.SCHEMA+'byDay', current.SCHEMA+'Monday', True)
        fact('schedule', current.SCHEMA+'startTime', '09:17:00', datatype=current.XSD+'time')
    return dict(rows=rows, count=len(rows), truncated=False)


def main():
    base = '82c0f0394b06acbb2e3738a6bb7ec5bb7f1160cf'
    source = subprocess.check_output(['git', 'show', base+':shantytown/quipu_jobs.py'], cwd=SOURCE)
    old = types.ModuleType('shantytown._calendar_demo_base')
    old.__package__ = 'shantytown'
    sys.modules[old.__name__] = old
    exec(compile(source, '<pinned-base-decoder>', 'exec'), old.__dict__)
    try:
        old.decode_catalogue(snapshot(True))
    except old.JobRefused as exc:
        print('Base', base, 'calendar refused:', exc)
    else:
        raise AssertionError('base unexpectedly admits the weekly form')
    fixed_before, = old.decode_catalogue(snapshot(False))
    fixed_after, = current.decode_catalogue(snapshot(False))
    assert asdict(fixed_before) == asdict(fixed_after)
    print('Positive fixed control: identical decoded fields before/after')
    job, = current.decode_catalogue(snapshot(True))
    assert job.interval_s is None and job.weekday == 0 and job.local_time == '09:17'
    assert not job.enabled
    print('Candidate disabled weekly declaration:', json.dumps(asdict(job), sort_keys=True))
    print('SOURCE READ ONLY: no graph, TOML, runtime admission or firing')


if __name__ == '__main__':
    main()
