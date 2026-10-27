"""Over-budget inboxes retain exact counts and bounded, oldest-first ACKs."""
from datetime import datetime, timedelta, timezone

import pytest
from rdflib import Literal, URIRef

from shantytown import cli, seeds_inbox, seeds_inbox_window as window
from shantytown.inbox import TrackerInbox
from shantytown.sd import SdTracker
from test_inbox_read_progress import args
from test_seeds_inbox_single_observation import wire, add, PROOF, G


def tracker(monkeypatch):
    t = SdTracker(quipu=PROOF.quipu_url, prefix='demo')
    monkeypatch.setattr(t, 'prove_store', lambda: PROOF)
    monkeypatch.setattr(t, '_owner_rows', lambda *a, **k: pytest.fail('SDK hydration fallback'))
    monkeypatch.setattr(t, 'get', lambda *a: pytest.fail('per-item SDK hydration'))
    return t


def test_over_budget_lab_counts_lists_and_drains_oldest_batch(wire, monkeypatch, capsys):
    data, queries = wire
    count = 1700
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    identifiers = [f'demo-{i:04}' for i in range(count)]
    for i, identifier in enumerate(identifiers):
        graph, subject = add(data, identifier, title=f'inbox: payload-{i}')
        graph.add((subject, URIRef(window.sp.SCHEMA+'dateCreated'),
                   Literal((origin + timedelta(seconds=i)).isoformat())))
    # This is beyond the old expanded-field budget, not an empty mock queue.
    assert not seeds_inbox.read(PROOF, 'worker').complete
    t = tracker(monkeypatch)
    box = TrackerInbox(t, lambda: pytest.fail('whole inbox listing'), items_for=t.inbox_items)
    monkeypatch.setattr(box, 'unread', lambda *a: pytest.fail('full metadata read'))
    monkeypatch.setattr(cli, '_inbox', lambda *a, **k: box)
    writes = []
    def close(identifier, **changes):
        assert changes == {'status': 'closed'}
        writes.append(identifier)
        subject = URIRef(window.sp.SEEDS+'item/'+identifier)
        data.graph(URIRef(G)).set((subject, URIRef(window.sp.SEEDS+'ontology/status'), Literal('closed')))
    monkeypatch.setattr(t, 'update', close)

    queries.clear()
    command = args(); command.count = True
    assert cli._inbox_read(command, 'worker') == cli.OK
    assert capsys.readouterr().out.strip() == str(count)
    assert len(queries) == 1 and 'COUNT(DISTINCT ?s)' in queries[0]
    assert 'priority' not in queries[0] and 'dateCreated' not in queries[0]
    assert not writes

    command = args(); command.read = False
    assert cli._inbox_read(command, 'worker') == cli.OK
    output = capsys.readouterr().out
    assert f'showing 100 of {count}' in output
    assert 'payload-1699' in output and 'payload-0\n' not in output
    assert not writes

    assert cli._inbox_read(args(), 'worker') == cli.OK
    assert writes == identifiers[:15]
    assert f'{count-15} snapshot message(s) not attempted' in capsys.readouterr().out
    assert box.unread_count('worker') == count-15
    assert all('LIMIT 10000' in q or 'COUNT(DISTINCT ?s)' in q
               or 'LIMIT 100' in q or 'LIMIT 15' in q for q in queries)


def test_count_checks_all_owned_statuses_but_not_message_fields(wire):
    data, _ = wire
    graph, subject = add(data)
    graph.set((subject, URIRef(window.sp.SEEDS+'ontology/priority'), Literal('bad')))
    assert window.count(PROOF, 'worker').exact() == 1
    add(data, 'demo-bad', title='ordinary work', status=None)
    assert not window.count(PROOF, 'worker').complete
    # One valid status is sufficient, matching the existing owner-status guard.
    graph.add((URIRef(window.sp.SEEDS+'item/demo-bad'),
               URIRef(window.sp.SEEDS+'ontology/status'), Literal('open')))
    assert window.count(PROOF, 'worker').exact() == 1


def test_counts_deduplicate_owner_spellings_and_refuse_graph_shadows(wire):
    data, _ = wire
    graph, subject = add(data)
    graph.add((subject, URIRef(window.sp.SCHEMA+'agent'), URIRef(window.sp.SEEDS+'principal/worker')))
    assert window.count(PROOF, 'worker').exact() == 1
    add(data, graph=G+'#seeds-ephemeral')
    assert not window.count(PROOF, 'worker').complete


def test_unknown_count_and_window_never_look_empty_or_fall_back(wire, monkeypatch, capsys):
    data, _ = wire
    add(data)
    t = tracker(monkeypatch)
    box = TrackerInbox(t, lambda: pytest.fail('whole inbox listing'), items_for=t.inbox_items)
    monkeypatch.setattr(cli, '_inbox', lambda *a, **k: box)
    monkeypatch.setattr(window.sp, '_query', lambda *a, **k: (_ for _ in ()).throw(OSError('fixture offline')))
    command = args(); command.count = True
    assert cli._inbox_read(command, 'worker') == cli.CANNOT_TELL
    output = capsys.readouterr()
    assert output.out == '' and 'could not tell' in output.err
    assert t._native_projection is not False


def test_legacy_count_requires_positive_marker(wire):
    data, _ = wire
    assert window.count(PROOF, 'worker').exact() == 0
    data.graph(URIRef(G)).add((URIRef(G+'/legacy'),
        URIRef(window.sp.SEEDS+'ontology/revision'), Literal(1)))
    with pytest.raises(seeds_inbox.LegacyInboxSchema):
        window.count(PROOF, 'worker')


@pytest.mark.parametrize('limit', [0, 101, True])
def test_bad_window_bound_is_unknown(wire, limit):
    assert not window.page_ids(PROOF, 'worker', limit=limit).complete
