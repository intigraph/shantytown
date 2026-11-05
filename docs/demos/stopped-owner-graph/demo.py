"""Offline library demo; a synthetic in-memory graph receiver, no HTTP."""
import json
from pathlib import Path
import re
import sys
import tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from shantytown.owned_work import OwnedWork
try:
    from shantytown import owned_work_graph as graph
except ImportError:
    graph = None

class Receiver:
    onto = 'https://example.test/ontology/'
    def __init__(self):
        self.rows = {}
        self.writes = 0
    def _query(self, query):
        iri = re.search(r'WHERE \{ <([^>]+)>', query).group(1)
        return self.rows.get(iri, [])
    def _knot(self, turtle):
        self.writes += 1
        iri = re.match(r'<([^>]+)>', turtle).group(1)
        value = re.search(r'<http://www.w3.org/2000/01/rdf-schema#comment> ("(?:\\.|[^"\\])*")', turtle).group(1)
        payload = json.loads(value)
        self.rows[iri] = [dict(payload=payload, revision=json.loads(payload)['revision'])]
    def set_comment(self, iri, payload):
        self.writes += 1
        self.rows[iri] = [dict(payload=payload)]

with tempfile.TemporaryDirectory(prefix='owned-demo-') as folder:
    root = Path(folder)
    state = OwnedWork(root)
    receiver = Receiver()
    state.launch('worker', now=100)
    if graph:
        graph._set_comment = lambda reg, iri, payload: reg.set_comment(iri, payload)
        graph.flush(root, receiver)
    state.stop('worker', at=90)
    if not graph:
        print(json.dumps(dict(trigger='stop after launch, clock moved backwards',
                              local_state=state.snapshot()['worker']['state'],
                              graph_observations=0, held_work_source='unavailable')))
    else:
        graph.flush(root, receiver)
        def show(trigger):
            _, head = graph._head(receiver, graph.producer(state.root))
            print(json.dumps(dict(trigger=trigger, head_revision=head['revision'],
                                  state=head['agents'][0]['state'], complete=head['complete'])))
        show('same stop after launch, clock moved backwards')
        count = receiver.writes
        state.stop('worker', at=500)
        graph.flush(root, receiver)
        assert receiver.writes == count
        print(json.dumps(dict(trigger='repeat same stop', extra_graph_writes=0)))
        state.launch('worker', now=80)
        graph.flush(root, receiver)
        show('sanctioned restart, clock still backwards')
        with state.locked() as states:
            states['worker'].update(graph_revision=1, state='stopped')
        try:
            graph.flush(root, receiver)
        except ValueError as error:
            assert 'replay refused' in str(error)
            print(json.dumps(dict(trigger='replay older local revision', result='REFUSED; newer head retained')))
        else:
            raise AssertionError('older state replaced current head')
