"""Restoration is explicit; active registry reads keep excluding retired crew."""
import json
from dataclasses import replace

import pytest

from shantytown.answer import Answer
from shantytown.files import FilesRegistry
from shantytown.protocols import Agent
from shantytown.quipu import QuipuRegistry, QuipuWriteRejected, all_query

ONTO = 'https://crew.test/'


def registry(tmp_path):
    reg = QuipuRegistry(server='http://example.invalid', onto=ONTO, root=tmp_path)
    local = Agent('leader', role='lead', reports_to='chief', host='host',
                  harness='claude', workspace=str(tmp_path), pane='leader', dangerous=True)
    FilesRegistry(tmp_path / 'crew').set(local)
    reg.all = lambda: Answer.complete_read([], how='active roster')
    rows = [{'s': ONTO + 'chief'},
            {'s': ONTO + 'leader', 'rt': ONTO + 'chief', 'h': ONTO + 'host', 'cs': 'retired'},
            {'s': ONTO + 'worker', 'rt': ONTO + 'leader'}]
    reg._query_answer = lambda _: Answer.complete_read(rows, how='lifecycle fixture')
    reg.role_sets = lambda: Answer.complete_read({}, how='fixture')
    return reg, local, rows


def test_explicit_lookup_preserves_lead_reports_and_actual_launch_configuration(tmp_path):
    reg, local, rows = registry(tmp_path)
    with pytest.raises(LookupError):
        reg.get('leader')
    card = reg.get_for_lifecycle('leader')
    assert (card.role, card.reports_to, card.host) == ('lead', 'chief', 'host')
    assert (card.harness, card.workspace, card.pane) == (local.harness, local.workspace, local.pane)
    assert card.retired is True
    assert 'FILTER(!bound(?cs))' in all_query(onto=ONTO)
    assert 'FILTER(!bound(?cs))' not in all_query(onto=ONTO, include_inactive=True)


@pytest.mark.parametrize('status', ['never-instantiated', None])
def test_restoration_never_invents_an_agent_or_arms_never_instantiated_member(tmp_path, status):
    reg, _, rows = registry(tmp_path)
    rows[1]['cs'] = status
    with pytest.raises(LookupError):
        reg.get_for_lifecycle('leader')


def test_unretirement_removes_exact_literal_only_and_verifies_placement(tmp_path, monkeypatch):
    reg, local, rows = registry(tmp_path)
    card = reg.get_for_lifecycle('leader')
    requests = []
    monkeypatch.setattr('shantytown.quipu_auth.write_headers', lambda _: {'Content-Type': 'application/json'})
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"tx_id":7,"retracted":1}'
    def send(request, **kw):
        requests.append((request.full_url, json.loads(request.data)))
        reg.all = lambda: Answer.complete_read([replace(card, retired=False)], how='restored')
        return Response()
    monkeypatch.setattr('urllib.request.urlopen', send)
    reg.set_retirement(card, False)
    assert requests == [('http://example.invalid/retract', dict(entity=ONTO+'leader',
                          predicate=ONTO+'crewStatus', value='retired'))]


def test_noop_receipt_is_not_a_successful_restoration(tmp_path, monkeypatch):
    reg, _, _ = registry(tmp_path)
    card = reg.get_for_lifecycle('leader')
    monkeypatch.setattr('shantytown.quipu_auth.write_headers', lambda _: {})
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"tx_id":0,"retracted":0}'
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **kw: Response())
    with pytest.raises(QuipuWriteRejected):
        reg.set_retirement(card, False)


@pytest.mark.parametrize('receipt', [dict(tx_id=-1, retracted=1),
                                    dict(tx_id=7, retracted=1, conforms=False)])
def test_invalid_or_nonconforming_receipt_cannot_restore(tmp_path, monkeypatch, receipt):
    reg, _, _ = registry(tmp_path)
    card = reg.get_for_lifecycle('leader')
    monkeypatch.setattr('shantytown.quipu_auth.write_headers', lambda _: {})
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return json.dumps(receipt).encode()
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **kw: Response())
    with pytest.raises(QuipuWriteRejected):
        reg.set_retirement(card, False)
