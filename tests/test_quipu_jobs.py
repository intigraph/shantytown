"""Scoped job declarations: adversarial RDF cells and complete-read controls."""
import copy
import io
import json
import urllib.error

import pytest

from shantytown import quipu_jobs as q

JOB = 'urn:example:job'
EVENT = 'urn:example:occurrences'
SCHEDULE = 'urn:example:schedule'


def catalogue():
    rows = []
    def fact(s, p, o, iri=False, datatype=q.XSD+'string'):
        row = dict(s=s, p=p, o=o, subjectIRI=True, objectIRI=iri)
        if not iri:
            row['datatype'] = datatype
        rows.append(row)
    for s, kind in ((JOB, 'Action'), (EVENT, 'Event'), (SCHEDULE, 'Schedule')):
        fact(s, q.RDF_TYPE, q.SCHEMA+kind, True)
    fact(EVENT, q.SCHEMA+'eventSchedule', SCHEDULE, True)
    fact(EVENT, q.SCHEMA+'potentialAction', JOB, True)
    for field, value in (('name', 'review'), ('identifier', 'revision1')):
        fact(JOB, q.SCHEMA+field, value)
    fact(JOB, q.QUECHUA+'sourceKind', 'declared')
    fact(JOB, q.QUECHUA+'owner', 'operator')
    fact(JOB, q.QUECHUA+'enabled', True, datatype=q.XSD+'boolean')
    fact(JOB, q.SCHEMA+'location', 'urn:example:host', True)
    fact(JOB, q.SCHEMA+'target', 'urn:example:manifest:revision1', True)
    fact(SCHEDULE, q.SCHEMA+'repeatFrequency', 'PT10M', datatype=q.XSD+'duration')
    fact(SCHEDULE, q.SCHEMA+'scheduleTimezone', 'UTC')
    fact(SCHEDULE, q.SCHEMA+'startDate', '2026-01-01T00:00:00Z', datatype=q.XSD+'dateTime')
    return dict(count=len(rows), rows=rows, truncated=False)


def row_for(body, predicate):
    return next(r for r in body['rows'] if r['p'] == predicate)


def test_decode_uses_actual_rdf_kinds_and_preserves_disabled_declarations():
    body = catalogue()
    before = copy.deepcopy(body)
    job, = q.decode_catalogue(body)
    assert (job.iri, job.host, job.target, job.interval_s, job.anchor_s) == (
        JOB, 'urn:example:host', 'urn:example:manifest:revision1', 600, 1767225600)
    assert body == before, 'read/parse must not mutate the snapshot'
    row_for(body, q.QUECHUA+'enabled')['o'] = False
    disabled, = q.decode_catalogue(body)
    assert disabled.enabled is False and disabled.iri == job.iri


@pytest.mark.parametrize('predicate', [q.SCHEMA+'name', q.SCHEMA+'identifier',
    q.QUECHUA+'owner', q.QUECHUA+'sourceKind', q.QUECHUA+'enabled',
    q.SCHEMA+'location', q.SCHEMA+'target', q.SCHEMA+'eventSchedule',
    q.SCHEMA+'potentialAction', q.SCHEMA+'startDate', q.SCHEMA+'scheduleTimezone'])
def test_missing_field_does_not_drop_a_job_into_an_empty_success(predicate):
    body = catalogue()
    body['rows'] = [r for r in body['rows'] if r['p'] != predicate]
    body['count'] = len(body['rows'])
    with pytest.raises(q.JobRefused):
        q.decode_catalogue(body)


@pytest.mark.parametrize('predicate', [q.SCHEMA+'location', q.SCHEMA+'target'])
def test_uri_looking_literal_is_not_an_admitted_iri(predicate):
    body = catalogue()
    row_for(body, predicate).update(o='https://example.org/command', objectIRI=False,
                                    datatype=q.XSD+'string')
    with pytest.raises(q.JobRefused, match='RDF term kind'):
        q.decode_catalogue(body)


def test_duplicate_revision_refuses_instead_of_selecting_one():
    body = catalogue()
    row = dict(row_for(body, q.SCHEMA+'identifier'), o='revision2')
    body['rows'].append(row)
    body['count'] += 1
    with pytest.raises(q.JobRefused, match='exactly one'):
        q.decode_catalogue(body)


@pytest.mark.parametrize('value,datatype', [('true', q.XSD+'string'), ('maybe', q.XSD+'boolean')])
def test_nonempty_string_is_not_true_enablement(value, datatype):
    body = catalogue()
    row_for(body, q.QUECHUA+'enabled').update(o=value, datatype=datatype)
    with pytest.raises(q.JobRefused):
        q.decode_catalogue(body)


@pytest.mark.parametrize('anchor', ['2026-01-01T00:00:00', '2026-01-01T00:00:00-00:00',
                                    '2026-01-01T00:00:00.000000001Z', '2026-02-30T00:00:00Z'])
def test_naive_unknown_offset_fractional_or_invalid_anchor_refuses(anchor):
    body = catalogue()
    row_for(body, q.SCHEMA+'startDate')['o'] = anchor
    with pytest.raises(q.JobRefused):
        q.decode_catalogue(body)


@pytest.mark.parametrize('duration', ['PT0S', '-PT1M', 'PT1S', 'P1M', 'P', 'P1DT', 'not-a-duration'])
def test_unsupported_interval_is_not_approximated(duration):
    body = catalogue()
    row_for(body, q.SCHEMA+'repeatFrequency')['o'] = duration
    with pytest.raises(q.JobRefused):
        q.decode_catalogue(body)


def test_invalid_zone_refuses_and_calendar_qualifier_cannot_be_ignored():
    body = catalogue()
    row_for(body, q.SCHEMA+'scheduleTimezone')['o'] = 'Invalid/Nowhere'
    with pytest.raises(q.JobRefused, match='timezone'):
        q.decode_catalogue(body)
    body = catalogue()
    body['rows'].append(dict(s=SCHEDULE, p=q.SCHEMA+'byDay', o=q.SCHEMA+'Monday',
                             subjectIRI=True, objectIRI=True))
    body['count'] += 1
    with pytest.raises(q.JobRefused, match='qualifier'):
        q.decode_catalogue(body)


@pytest.mark.parametrize('change', [dict(truncated=True), dict(count=0, rows=[]),
                                   dict(error='HTTP408'), dict(count=999), dict(truncated=None)])
def test_partial_failed_or_empty_snapshot_is_unknown(change):
    body = catalogue()
    body.update(change)
    with pytest.raises(q.JobsUnavailable):
        q.decode_catalogue(body)


def test_loss_of_query_typing_capability_is_unknown():
    body = catalogue()
    body['rows'][0].pop('objectIRI')
    with pytest.raises(q.JobsUnavailable):
        q.decode_catalogue(body)


class Response(io.BytesIO):
    pass


def test_transport_always_uses_explicit_graph_verbose_and_bounded_projection(monkeypatch):
    seen = []
    def answer(req, timeout):
        seen.append((req, timeout))
        return Response(json.dumps(catalogue()).encode())
    monkeypatch.setattr(q.urllib.request, 'urlopen', answer)
    jobs = q.JobCatalogue('urn:example:catalogue', server='http://localhost:3030').read()
    req, timeout = seen[0]
    assert len(jobs) == 1 and timeout == 10
    body = json.loads(req.data)
    assert body['graph'] == 'urn:example:catalogue' and body['verbose'] is True
    assert 'DATATYPE(?o)' in body['query'] and 'isIRI(?o)' in body['query']
    assert body['query'].endswith('LIMIT 4097')
    assert req.get_header('X-quipu-client') == 'st-jobs'


def test_http_refusal_does_not_retry_or_fall_back_to_default_graph(monkeypatch):
    calls = []
    def refused(req, timeout):
        calls.append(req)
        raise urllib.error.HTTPError(req.full_url, 408, 'timeout', {}, None)
    monkeypatch.setattr(q.urllib.request, 'urlopen', refused)
    with pytest.raises(q.JobsUnavailable):
        q.JobCatalogue('urn:example:catalogue', server='http://localhost:3030').read()
    assert len(calls) == 1


def test_missing_graph_refuses_before_http(monkeypatch):
    monkeypatch.setattr(q.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('network'))
    with pytest.raises(q.JobRefused):
        q.JobCatalogue('')


def test_orphaned_job_cannot_disappear_when_occurrence_type_is_removed():
    body = catalogue()
    body['rows'] = [r for r in body['rows'] if r['s'] != EVENT]
    body['count'] = len(body['rows'])
    with pytest.raises(q.JobsUnavailable):
        q.decode_catalogue(body)


def test_same_job_name_on_two_hosts_is_not_a_conflicting_identity():
    body = catalogue()
    second = copy.deepcopy(body['rows'])
    for row in second:
        row['s'] += ':other'
        if row['objectIRI'] and row['o'].startswith('urn:example:'):
            row['o'] += ':other'
    body['rows'] += second
    body['count'] = len(body['rows'])
    assert len(q.decode_catalogue(body)) == 2


def test_receiver_does_not_accept_a_pre_epoch_slot_anchor():
    body = catalogue()
    row_for(body, q.SCHEMA+'startDate')['o'] = '1960-01-01T00:00:00Z'
    with pytest.raises(q.JobRefused, match='epoch'):
        q.decode_catalogue(body)


def test_graph_cli_lists_typed_declarations_without_loading_toml(tmp_path, monkeypatch, capsys):
    from shantytown import cli, jobs
    monkeypatch.setattr(q.JobCatalogue, 'read', lambda self: q.decode_catalogue(catalogue()))
    monkeypatch.setattr(jobs, 'load', lambda *a: pytest.fail('graph mode read local TOML'))
    assert cli.main(['--root', str(tmp_path), 'work', 'jobs', '--graph',
                     'urn:example:catalogue', '--expect-job', JOB, 'list']) == cli.OK
    out = capsys.readouterr().out
    assert 'revision1' in out and '1 required identities verified' in out
    assert 'signed run status are UNKNOWN' in out
    assert not list(tmp_path.rglob('*')), 'read-only command created local state'


def test_graph_cli_deletion_control_does_not_accept_another_live_job(tmp_path, monkeypatch, capsys):
    from shantytown import cli
    monkeypatch.setattr(q.JobCatalogue, 'read', lambda self: q.decode_catalogue(catalogue()))
    assert cli.main(['--root', str(tmp_path), 'work', 'jobs', '--graph',
                     'urn:example:catalogue', '--expect-job', 'urn:example:removed',
                     'list']) == cli.CANNOT_TELL
    assert 'required job identities missing' in capsys.readouterr().err


@pytest.mark.parametrize('verb', [['list'], ['check'], ['run', 'review'], ['history', 'review']])
def test_graph_cli_never_falls_back_to_toml_on_unavailable_or_unimplemented_lane(
        tmp_path, monkeypatch, capsys, verb):
    from shantytown import cli, jobs
    monkeypatch.setattr(jobs, 'load', lambda *a: pytest.fail('unsafe TOML fallback'))
    def unavailable(self):
        raise q.JobsUnavailable('measured query refusal')
    monkeypatch.setattr(q.JobCatalogue, 'read', unavailable)
    rc = cli.main(['--root', str(tmp_path), 'work', 'jobs', '--graph',
                   'urn:example:catalogue', *verb])
    assert rc in (cli.CANNOT_TELL, cli.REFUSED)
    assert capsys.readouterr().err


def test_graph_check_cannot_claim_would_fire_from_declarations_alone(tmp_path, monkeypatch, capsys):
    from shantytown import cli
    monkeypatch.setattr(q.JobCatalogue, 'read', lambda self: q.decode_catalogue(catalogue()))
    assert cli.main(['--root', str(tmp_path), 'work', 'jobs', '--graph',
                     'urn:example:catalogue', 'check', 'review']) == cli.CANNOT_TELL
    out = capsys.readouterr().out
    assert 'firing eligibility is UNKNOWN' in out
    assert 'would fire' not in out and 'Membership coverage: UNKNOWN' in out
