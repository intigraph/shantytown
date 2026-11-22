"""An explicitly typed Ask needs no legacy title or label to stay off work queues."""
from datetime import datetime, timezone

from shantytown.ask_visibility import is_ask, refuse_deferral
from shantytown.feed_check import hauls
from shantytown.stop_event import _assigned_to
from shantytown.plate_capacity import real_work
from shantytown.overdue import findings
from shantytown.priority_advisory import workable
from shantytown.stranded_work import eligible
from shantytown import seeds_plate


def row(kind):
    return dict(id='test-1', title='Choose a color', issue_type=kind, status='open',
                assignee='worker', priority=1, labels=[], due_at='2026-01-01T00:00:00Z')


def test_explicit_ask_is_not_worker_work():
    ask, work = row('ask'), row('task') | {'id': 'test-2'}
    assert is_ask(ask) and not is_ask(work)
    assert not real_work(ask) and real_work(work)
    assert not workable(ask) and workable(work)
    assert not eligible(ask)
    assert _assigned_to('worker', [ask, work]) == [work]
    assert hauls([ask, work]) == {'worker': ['test-2']}
    assert findings([ask], datetime(2026, 1, 2, tzinfo=timezone.utc)) == []


def test_native_ready_count_excludes_assigned_and_unassigned_asks(monkeypatch):
    import pytest
    rdflib = pytest.importorskip('rdflib')
    from shantytown.sd import StoreProof
    graph = 'https://example.test/project/test'
    proof = StoreProof('--quipu', None, 'https://example.test', 'test', graph)
    data = rdflib.Dataset()
    g = data.graph(rdflib.URIRef(graph))
    for index, kind in enumerate(['ask', 'task']):
        subject = rdflib.URIRef(seeds_plate.SEEDS + 'item/test-' + str(index))
        g.add((subject, rdflib.RDF.type, rdflib.URIRef(seeds_plate.SCHEMA + 'Action')))
        for predicate, value in [('status', 'open'), ('issueType', kind), ('priority', 1)]:
            g.add((subject, rdflib.URIRef(seeds_plate.SEEDS + 'ontology/' + predicate), rdflib.Literal(value)))
        g.add((subject, rdflib.URIRef(seeds_plate.SCHEMA + 'identifier'), rdflib.Literal('test-' + str(index))))
        g.add((subject, rdflib.URIRef(seeds_plate.SCHEMA + 'name'), rdflib.Literal('Choose a color')))
    def query(proof, text, timeout):
        rows = [{str(k): v.toPython() for k, v in r.asdict().items()} for r in data.query(text)]
        return dict(rows=rows, count=len(rows), truncated=False)
    monkeypatch.setattr(seeds_plate, '_query', query)
    assert seeds_plate.ready_count(proof, now=datetime(2026, 1, 2, tzinfo=timezone.utc)) == 1
    assert seeds_plate.unassigned_counts(proof) == (1, 1)


def test_files_plate_and_exact_item_keep_the_type(tmp_path):
    from shantytown.files import FilesTracker, plate
    tracker = FilesTracker(tmp_path / 'items')
    tracker.update('test-1', **{k: v for k, v in row('ask').items() if k != 'id'},
                   unblocks='test-2', default='Wait', expires_at='2026-02-01T00:00:00Z')
    assert tracker.get('test-1').issue_type == 'ask'
    assert tracker.get('test-1').unblocks == 'test-2'
    assert plate(tracker, 'worker') is None
    tracker.update('test-2', title='Implement the choice', assignee='worker', status='open')
    assert plate(tracker, 'worker').id == 'test-2'
