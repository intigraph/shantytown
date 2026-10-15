"""Replay a read-only graph CLI demo against this checkout or --source BASE.

Only the HTTP response is a fixture. No graph mutation or command execution.
"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

source = Path(sys.argv[2]).resolve() if len(sys.argv) == 3 and sys.argv[1] == '--source' else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(source))
from shantytown import cli  # noqa: E402

schema = 'https://schema.org/'
quechua = 'https://scbrown.github.io/quechua/ns#'
xsd = 'http://www.w3.org/2001/XMLSchema#'
rdf_type = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
job, event, schedule = ('urn:example:'+name for name in ('review', 'occurrences', 'schedule'))
rows = []
def fact(subject, predicate, value, *, iri=False, datatype=xsd+'string'):
    row = dict(s=subject, p=predicate, o=value, subjectIRI=True, objectIRI=iri)
    if not iri:
        row['datatype'] = datatype
    rows.append(row)
for subject, kind in ((job, 'Action'), (event, 'Event'), (schedule, 'Schedule')):
    fact(subject, rdf_type, schema+kind, iri=True)
fact(event, schema+'potentialAction', job, iri=True)
fact(event, schema+'eventSchedule', schedule, iri=True)
for predicate, value in ((schema+'name', 'review'), (schema+'identifier', 'revision1'),
                         (quechua+'sourceKind', 'declared'), (quechua+'owner', 'operator')):
    fact(job, predicate, value)
fact(job, quechua+'enabled', True, datatype=xsd+'boolean')
fact(job, schema+'location', 'urn:example:host', iri=True)
fact(job, schema+'target', 'urn:example:manifest:revision1', iri=True)
fact(schedule, schema+'repeatFrequency', 'PT10M', datatype=xsd+'duration')
fact(schedule, schema+'scheduleTimezone', 'UTC')
fact(schedule, schema+'startDate', '2026-01-01T00:00:00Z', datatype=xsd+'dateTime')

def response(request, timeout):
    body = json.loads(request.data)
    assert body['graph'] == 'urn:example:catalogue' and body['verbose'] is True
    return io.BytesIO(json.dumps(dict(count=len(rows), rows=rows, truncated=False)).encode())

with tempfile.TemporaryDirectory() as root, patch('urllib.request.urlopen', response):
    for expected in (job, 'urn:example:removed'):
        args = ['work', 'jobs', '--graph', 'urn:example:catalogue', '--expect-job', expected, 'list']
        print('$ st ' + ' '.join(args), flush=True)
        # argparse on the base refuses new flags; retain its real output and rc.
        try:
            with contextlib.redirect_stderr(sys.stdout):
                rc = cli.main(['--root', root, *args])
        except SystemExit as exc:
            rc = exc.code
        print(f'exit={rc}', flush=True)
    assert not list(Path(root).rglob('*')), 'read surface created state'
